#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lancer-armagetron.py - pose par le template AMP TeamKit (recree a chaque Update).

    python3 lancer-armagetron.py installer               etape d'Update
    python3 lancer-armagetron.py lancer <port> <joueurs>  ligne de commande d'AMP

installer : extrait l'AppImage officielle du serveur (ArmagetronAdvancedDedicated.AppImage,
            telechargee par AMP) dans serveur/, sans FUSE (--appimage-extract).
lancer    : 1. lit reglages-amp.cfg (ecrit par AMP, en UTF-8) et perso.cfg ;
            2. ecrit config/settings_custom.cfg en Latin-1, le seul encodage du jeu
               (les emojis et autres caracteres impossibles sont retires, le tiret
               long devient -, etc.) ;
            3. lance armagetronad-dedicated, relaie la console d'AMP vers son entree
               (le serveur lit ses commandes sur stdin : SAY, KICK, BAN, PLAYERS...) ;
            4. filtre sa sortie : Latin-1 -> UTF-8, lignes repetitives retirees, et
               traduit les evenements PLAYER_ENTERED / PLAYER_LEFT / PLAYER_RENAMED
               du ladderlog en lignes « TeamKit : arrivee de X » / « depart de X »
               pour la liste des joueurs d'AMP ;
            5. ecrit « TeamKit : Armagetron Advanced pret sur le port N (UDP). » quand
               le serveur a ouvert son port ;
            6. a l'arret demande par AMP (SIGTERM), envoie QUIT au serveur.
"""
import ctypes
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import unicodedata

ICI = os.path.dirname(os.path.abspath(__file__))
APPIMAGE = os.path.join(ICI, 'ArmagetronAdvancedDedicated.AppImage')
SERVEUR = os.path.join(ICI, 'serveur')
BIN = os.path.join(SERVEUR, 'usr', 'bin', 'armagetronad-dedicated')
LIBS = os.path.join(SERVEUR, 'usr', 'lib')
CONFIG = os.path.join(ICI, 'config')
VAR = os.path.join(ICI, 'var')
DONNEES = os.path.join(ICI, 'donnees')
REGLAGES_AMP = os.path.join(ICI, 'reglages-amp.cfg')
PERSO = os.path.join(ICI, 'perso.cfg')
SORTIE = os.path.join(CONFIG, 'settings_custom.cfg')

# Noms exacts de la ligne « language » des fichiers de langue du jeu (language/*.txt).
LANGUES = ('Francais', 'American English', 'British English', 'Deutsch', 'Spanish',
           'Polish', 'Polish (bez znakow specjalnych)')

# Caracteres courants hors Latin-1 et leur equivalent affichable par le jeu.
REMPLACEMENTS = {
    '‐': '-', '‑': '-', '‒': '-', '–': '-', '—': '-', '―': '-',
    '−': '-', '‘': "'", '’': "'", '‚': "'", '′': "'",
    '“': '"', '”': '"', '„': '"', '″': '"', '…': '...',
    '€': 'EUR', 'œ': 'oe', 'Œ': 'OE', '•': '·', '‧': '·',
    '™': 'TM', '→': '->', '←': '<-', ' ': ' ', ' ': ' ',
    ' ': ' ', ' ': ' ', ' ': ' ', '\t': ' ',
}
# Invisibles qui accompagnent les emojis : retires sans le signaler.
INVISIBLES = {'​', '‌', '‍', '⁠', '﻿', '︎', '️'}


def dire(texte):
    """Ligne pour la console d'AMP."""
    sys.stdout.write(texte + '\n')
    sys.stdout.flush()


def vers_latin1(texte):
    """Rend un texte UTF-8 affichable par le jeu (Latin-1). Renvoie (texte, retires)."""
    sortie, retires = [], []
    for c in texte:
        n = ord(c)
        if c in REMPLACEMENTS:
            sortie.append(REMPLACEMENTS[c])
        elif 32 <= n < 127 or 160 <= n < 256:
            sortie.append(c)
        elif c in INVISIBLES or unicodedata.category(c) in ('Mn', 'Me'):
            continue
        else:
            # lettre accentuee hors Latin-1 (ex. « ŝ ») : sa lettre de base
            base = ''.join(x for x in unicodedata.normalize('NFKD', c)
                           if 32 <= ord(x) < 127 or 160 <= ord(x) < 256)
            if base:
                sortie.append(base)
            elif n >= 32:
                retires.append(c)
    return ''.join(sortie), retires


def sans_couleurs(texte):
    """Retire les codes couleur du jeu (0xRRGGBB, 0xRESETT)."""
    return re.sub(r'0x(?:[0-9a-fA-F]{6}|RESETT)', '', texte)


# ── reglages ────────────────────────────────────────────────────────────────

class Refus(Exception):
    pass


def entier(cle, valeur, mini, maxi):
    if not re.fullmatch(r'-?\d+', valeur or ''):
        raise Refus('%s : "%s" n\'est pas un nombre entier.' % (cle, valeur))
    v = int(valeur)
    if not mini <= v <= maxi:
        raise Refus('%s : %d hors des limites (%d a %d).' % (cle, v, mini, maxi))
    return str(v)


def texte_ligne(cle, valeur, avertir):
    """Valeur d'un reglage « ligne » (SERVER_NAME, MESSAGE_OF_DAY...).

    Le jeu lit tout le reste de la ligne : # n'y est PAS un commentaire. Il comprend
    \\n (retour a la ligne) et \\\\ (barre oblique inverse) ; une barre oblique inverse
    en fin de ligne colle la ligne suivante a la valeur."""
    v, retires = vers_latin1(valeur.strip())
    if retires:
        avertir('%s : caracteres que le jeu ne sait pas afficher, retires : %s'
                % (cle, ' '.join(retires)))
    if cle != 'MESSAGE_OF_DAY':
        # pas de saut de ligne ailleurs que dans le message d'accueil
        v = v.replace('\\', '\\\\')
    else:
        fin = len(v) - len(v.rstrip('\\'))
        if fin % 2:
            v += '\\'
    return v.strip()


def lire_reglages_amp(texte, avertir):
    """Lit reglages-amp.cfg (rendu par AMP) et renvoie les lignes du jeu, controlees."""
    attendues = ('SERVER_NAME', 'TALK_TO_MASTER', 'SERVER_OPTIONS', 'URL', 'TITLE_OF_DAY',
                 'MESSAGE_OF_DAY', 'LANGUAGE_FIRST', 'LIMIT_ROUNDS', 'MIN_PLAYERS',
                 'TEAM_MAX_PLAYERS', 'SPEED_FACTOR', 'SIZE_FACTOR')
    vus = {}
    for brute in texte.splitlines():
        ligne = brute.rstrip('\r')
        if not ligne.strip() or ligne.lstrip().startswith('#'):
            continue
        cle, _, valeur = ligne.partition(' ')
        if cle in attendues and cle not in vus:
            vus[cle] = valeur
        else:
            # une valeur contenant un vrai retour a la ligne deborde sur la ligne suivante
            avertir('reglages-amp.cfg : ligne ignoree : %s' % ligne[:80])
    manque = [c for c in attendues if c not in vus]
    if manque:
        raise Refus('reglages-amp.cfg incomplet (%s) : lance Update pour reprendre le modele.'
                    % ', '.join(manque))
    lignes = []

    nom = texte_ligne('SERVER_NAME', vus['SERVER_NAME'], avertir)
    if not sans_couleurs(nom).strip():
        avertir('SERVER_NAME : nom vide, remplace par "TeamKit".')
        nom = 'TeamKit'
    lignes.append('SERVER_NAME ' + nom)

    ttm = vus['TALK_TO_MASTER'].strip()
    if ttm not in ('0', '1'):
        raise Refus('TALK_TO_MASTER : 0 ou 1, pas "%s".' % ttm)
    lignes.append('TALK_TO_MASTER ' + ttm)

    options = texte_ligne('SERVER_OPTIONS', vus['SERVER_OPTIONS'], avertir)
    if len(options) > 240:
        avertir('SERVER_OPTIONS : %d caracteres, le jeu coupe a 240.' % len(options))
    lignes.append('SERVER_OPTIONS ' + options)

    url, retires = vers_latin1(vus['URL'].strip())
    if ' ' in url or retires:
        avertir('URL : espaces et caracteres speciaux retires.')
        url = url.replace(' ', '')
    if len(url) > 75:
        avertir('URL : %d caracteres, le jeu coupe a 75.' % len(url))
    if url.startswith(('"', "'")):
        raise Refus('URL : ne doit pas commencer par un guillemet.')
    lignes.append('URL ' + url.replace('\\', '/') if url else 'URL ""')

    lignes.append('TITLE_OF_DAY ' + texte_ligne('TITLE_OF_DAY', vus['TITLE_OF_DAY'], avertir))
    lignes.append('MESSAGE_OF_DAY ' + texte_ligne('MESSAGE_OF_DAY', vus['MESSAGE_OF_DAY'], avertir))

    langue = vus['LANGUAGE_FIRST'].strip()
    if langue not in LANGUES:
        raise Refus('LANGUAGE_FIRST : langue inconnue "%s".' % langue)
    lignes.append('LANGUAGE_FIRST ' + langue)

    lignes.append('LIMIT_ROUNDS ' + entier('LIMIT_ROUNDS', vus['LIMIT_ROUNDS'].strip(), 1, 1000))
    mini = entier('MIN_PLAYERS', vus['MIN_PLAYERS'].strip(), 0, 16)
    lignes.append('MIN_PLAYERS ' + mini)
    lignes.append('TEAM_MAX_PLAYERS ' + entier('TEAM_MAX_PLAYERS', vus['TEAM_MAX_PLAYERS'].strip(), 1, 16))
    lignes.append('SPEED_FACTOR ' + entier('SPEED_FACTOR', vus['SPEED_FACTOR'].strip(), -4, 4))
    lignes.append('SIZE_FACTOR ' + entier('SIZE_FACTOR', vus['SIZE_FACTOR'].strip(), -4, 4))
    return lignes


def construire(texte_amp, texte_perso, port, joueurs, avertir):
    """Contenu de settings_custom.cfg (str, a ecrire en Latin-1)."""
    lignes = [
        '# settings_custom.cfg - REECRIT A CHAQUE DEMARRAGE par lancer-armagetron.py.',
        '# Ne le modifie pas : change les reglages dans AMP, ou ecris dans perso.cfg.',
        '',
        '# --- reglages d\'AMP (reglages-amp.cfg) ---',
    ]
    lignes += lire_reglages_amp(texte_amp, avertir)
    lignes += ['', '# --- perso.cfg ---']
    for brute in texte_perso.splitlines():
        ligne, retires = vers_latin1(brute.rstrip('\r'))
        if retires and not ligne.lstrip().startswith('#'):
            avertir('perso.cfg : caracteres retires : %s' % ' '.join(retires))
        lignes.append(ligne)
    lignes += [
        '',
        '# --- impose par le template (apres perso.cfg) ---',
        '# port et places donnes par AMP',
        'SERVER_PORT %d' % port,
        'MAX_CLIENTS %d' % joueurs,
        '# evenements du ladderlog recopies sur la console : liste des joueurs d\'AMP',
        'CONSOLE_LADDER_LOG 1',
        'LADDERLOG_WRITE_PLAYER_ENTERED 1',
        'LADDERLOG_WRITE_PLAYER_LEFT 1',
        'LADDERLOG_WRITE_PLAYER_RENAMED 1',
        'CONSOLE_DECORATE_ID 1',
        '',
    ]
    return '\n'.join(lignes)


# ── filtre de la sortie du serveur ──────────────────────────────────────────

# Lignes repetees en boucle par le serveur, inutiles dans AMP.
BRUIT = re.compile(
    r'^\[\d+\] (?:'
    r'Answering ping poll from \S+'                      # chaque joueur qui regarde la liste
    r'|En attente de joueurs reels.*'                    # en boucle tant que personne ne joue
    r'|Waiting for real players.*'
    r'|Command HUD_CACHE_THRESHOLD unknown\.'            # vient du settings.cfg officiel
    r'|Ping change de \d+ a \d+\.|Ping changed from \d+ to \d+\.'
    r')?$')


class Filtre:
    """Transforme chaque ligne du serveur (deja en str) en 0, 1 ou 2 lignes pour AMP."""

    def __init__(self, port):
        self.port = port
        self.noms = {}          # nom de journal -> nom affiche
        self.pret = False

    @staticmethod
    def nom_affiche(brut, secours):
        nom = sans_couleurs(brut).strip()
        return nom or secours

    def ligne(self, l):
        if l.startswith('[L] '):
            mots = l[4:].split(' ')
            evt = mots[0]
            if evt == 'PLAYER_ENTERED' and len(mots) >= 3:
                nom = self.nom_affiche(' '.join(mots[3:]), mots[1])
                self.noms[mots[1]] = nom
                return ['TeamKit : arrivee de %s' % nom]
            if evt == 'PLAYER_LEFT' and len(mots) >= 2:
                nom = self.noms.pop(mots[1], mots[1])
                return ['TeamKit : depart de %s' % nom]
            if evt == 'PLAYER_RENAMED' and len(mots) >= 4:
                ancien = self.noms.pop(mots[1], mots[1])
                nom = self.nom_affiche(' '.join(mots[4:]), mots[2])
                self.noms[mots[2]] = nom
                if nom == ancien:
                    return []
                return ['TeamKit : depart de %s' % ancien, 'TeamKit : arrivee de %s' % nom]
            return []           # le reste du ladderlog reste dans var/ladderlog.txt
        if BRUIT.match(l):
            return []
        if l.startswith('TeamKit'):
            l = ' ' + l          # seules nos lignes commencent par « TeamKit »
        sortie = [l]
        if not self.pret and re.fullmatch(r'\[\d+\] Bound socket to \S+:%d\.' % self.port, l):
            self.pret = True
            sortie.append('TeamKit : Armagetron Advanced pret sur le port %d (UDP).' % self.port)
        return sortie


# ── installer (etape d'Update) ──────────────────────────────────────────────

def installer():
    if not os.path.isfile(APPIMAGE) or os.path.getsize(APPIMAGE) < 500000:
        dire('ERREUR : %s absent ou incomplet : l\'etape de telechargement a echoue.'
             % os.path.basename(APPIMAGE))
        return 1
    with open(APPIMAGE, 'rb') as f:
        if f.read(4) != b'\x7fELF':
            dire('ERREUR : le fichier telecharge n\'est pas une AppImage (pas un ELF).')
            return 1
    os.chmod(APPIMAGE, 0o755)
    tmp = os.path.join(ICI, '.extraction')
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    # --appimage-extract : pas besoin de FUSE (absent des conteneurs AMP).
    r = subprocess.run([APPIMAGE, '--appimage-extract'], cwd=tmp,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
    neuf = os.path.join(tmp, 'squashfs-root')
    if r.returncode or not os.path.isfile(os.path.join(neuf, 'usr', 'bin', 'armagetronad-dedicated')):
        dire('ERREUR : extraction de l\'AppImage impossible : %s'
             % r.stderr.decode('utf-8', 'replace').strip()[-300:])
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    ancien = SERVEUR + '.ancien'
    shutil.rmtree(ancien, ignore_errors=True)
    if os.path.isdir(SERVEUR):
        os.rename(SERVEUR, ancien)
    os.rename(neuf, SERVEUR)
    shutil.rmtree(ancien, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    for d in (CONFIG, VAR, DONNEES):
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(PERSO):
        with open(PERSO, 'w', encoding='utf-8') as f:
            f.write(PERSO_MODELE)
    env = dict(os.environ, LD_LIBRARY_PATH=LIBS)
    r = subprocess.run([BIN, '--version'], env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=60)
    version = r.stdout.decode('latin-1').strip()
    dire(version or 'ERREUR : le serveur ne repond pas a --version.')
    if r.returncode or 'armagetronad-dedicated version' not in version:
        manque = subprocess.run(['ldd', BIN], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT).stdout.decode('latin-1')
        dire('Bibliotheques manquantes :\n' + '\n'.join(
            l for l in manque.splitlines() if 'not found' in l))
        return 1
    dire('TeamKit : serveur installe dans serveur/ (AppImage officielle extraite).')
    return 0


PERSO_MODELE = """\
# perso.cfg - tes reglages Armagetron en plus, un par ligne : NOM valeur
# Lu a chaque demarrage APRES les reglages d'AMP (il peut donc les remplacer),
# puis converti en Latin-1 (l'encodage du jeu). Le template ne l'ecrase jamais.
# Une ligne qui commence par # est ignoree. ATTENTION : apres un reglage texte
# (SERVER_NAME, MESSAGE_OF_DAY...), un # n'est PAS un commentaire.
# Liste des reglages : https://wiki.armagetronad.org/index.php/Console_Commands
#
# Exemples (retire le # devant pour les activer) :
# WALLS_LENGTH 300                  # longueur des traces des motos (-1 = infinie)
# AI_IQ 80                          # niveau des bots (0 a 100)
# LIMIT_SCORE 100                   # score qui termine un match
# ROUND_CONSOLE_MESSAGE Rejoins-nous sur discord.gg/EuAjGMYPHY
# INCLUDE examples/death_zone.cfg   # variante fournie avec le jeu
"""


# ── lancer ──────────────────────────────────────────────────────────────────

def rotation(nom, limite=20 * 1024 * 1024):
    chemin = os.path.join(VAR, nom)
    try:
        if os.path.getsize(chemin) > limite:
            os.replace(chemin, chemin + '.1')
            dire('TeamKit : %s depasse 20 Mo, renomme en %s.1.' % (nom, nom))
    except OSError:
        pass


def lancer(port, joueurs):
    try:
        port = int(entier('port', port, 1024, 65535))
        joueurs = int(entier('joueurs', joueurs, 1, 32))
    except Refus as e:
        dire('ERREUR : ' + str(e))
        return 1
    if not os.access(BIN, os.X_OK):
        dire('ERREUR : %s absent. Lance Update (il telecharge et extrait le serveur).' % BIN)
        return 1
    if not os.path.isfile(REGLAGES_AMP):
        dire('ERREUR : reglages-amp.cfg absent. AMP l\'ecrit au demarrage a partir de '
             'AMP_reglages.cfg : lance Update.')
        return 1
    for d in (CONFIG, VAR, DONNEES):
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(PERSO):
        with open(PERSO, 'w', encoding='utf-8') as f:
            f.write(PERSO_MODELE)
    with open(REGLAGES_AMP, encoding='utf-8', errors='replace') as f:
        texte_amp = f.read()
    with open(PERSO, encoding='utf-8', errors='replace') as f:
        texte_perso = f.read()
    try:
        contenu = construire(texte_amp, texte_perso, port, joueurs,
                             lambda m: dire('TeamKit : ' + m))
    except Refus as e:
        dire('ERREUR : ' + str(e))
        dire('Corrige ce reglage dans l\'onglet Configuration d\'AMP, puis relance.')
        return 1
    with open(SORTIE, 'w', encoding='latin-1', newline='\n') as f:
        f.write(contenu)
    rotation('ladderlog.txt')
    rotation('scorelog.txt')

    libc = ctypes.CDLL(None, use_errno=True)

    def pdeathsig():
        # si ce script est tue net, le serveur recoit SIGTERM au lieu de garder le port
        libc.prctl(1, signal.SIGTERM)

    env = dict(os.environ, LD_LIBRARY_PATH=LIBS)
    proc = subprocess.Popen(
        [BIN, '--userconfigdir', CONFIG, '--vardir', VAR, '--userdatadir', DONNEES],
        cwd=ICI, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, preexec_fn=pdeathsig)
    verrou = threading.Lock()

    def envoyer(commande):
        with verrou:
            try:
                proc.stdin.write(commande.encode('latin-1') + b'\n')
                proc.stdin.flush()
                return True
            except (BrokenPipeError, OSError, ValueError):
                return False

    arret = {'demande': False}

    def arreter(signum, frame):
        if arret['demande']:
            return
        arret['demande'] = True
        dire('TeamKit : arret demande, fermeture du serveur (QUIT).')
        envoyer('QUIT')

        def forcer():
            for _ in range(20):
                if proc.poll() is not None:
                    return
                time.sleep(0.5)
            proc.terminate()
            time.sleep(3)
            if proc.poll() is None:
                proc.kill()
        threading.Thread(target=forcer, daemon=True).start()

    signal.signal(signal.SIGTERM, arreter)
    signal.signal(signal.SIGINT, arreter)

    def relais():
        # Console d'AMP (UTF-8) -> entree du serveur (Latin-1), une commande par ligne.
        # os.read et pas sys.stdin : un fil bloque dans sys.stdin garde son verrou et
        # Python plante en s'arretant (« could not acquire lock for <stdin> », vu le 10/10).
        reste = b''
        while True:
            try:
                bloc = os.read(0, 4096)
            except OSError:
                return
            if not bloc:
                return
            *lignes, reste = (reste + bloc).split(b'\n')
            for brute in lignes:
                l = brute.decode('utf-8', 'replace').strip()
                if not l:
                    continue
                l, _ = vers_latin1(l)
                if not envoyer(l):
                    dire('TeamKit : commande non transmise, le serveur ne repond plus.')
                    return
    threading.Thread(target=relais, daemon=True).start()

    filtre = Filtre(port)

    def surveiller_pret():
        time.sleep(30)
        if not filtre.pret and proc.poll() is None:
            dire('TeamKit : ATTENTION, le port %d n\'est toujours pas ouvert apres 30 secondes.' % port)
    threading.Thread(target=surveiller_pret, daemon=True).start()

    for brute in proc.stdout:
        l = brute.decode('latin-1').rstrip('\r\n')
        for s in filtre.ligne(l):
            dire(s)
    code = proc.wait()
    if code and not arret['demande']:
        dire('TeamKit : le serveur s\'est arrete (code %d).' % code)
    return code


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except AttributeError:
        pass
    os.environ.setdefault('LANG', 'C.UTF-8')
    if len(argv) >= 1 and argv[0] == 'installer':
        return installer()
    if len(argv) == 3 and argv[0] == 'lancer':
        code = lancer(argv[1], argv[2])
        # sortie immediate : les fils de relais (bloques en lecture) ne doivent pas
        # retarder ni faire planter l'arret de Python
        sys.stdout.flush()
        os._exit(code if 0 <= code < 256 else 1)
    dire('Usage : lancer-armagetron.py installer | lancer <port> <joueurs>')
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
