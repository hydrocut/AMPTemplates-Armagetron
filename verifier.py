# -*- coding: utf-8 -*-
"""
Controle du template avant de le pousser (meme role que ceux de Wesnoth, Freeciv, DDNet).

    python verifier.py

1. tous les JSON se parsent ;
2. le .kvp ne reference que des fichiers presents, le port principal existe, le bloc
   Console.* / Limits.* est complet, la console d'AMP ecrit dans le lanceur, port et
   places sont passes au lanceur ;
3. chaque reglage expose dans AMP arrive dans le modele scripts/AMP_reglages.cfg (rendu
   par AMP en reglages-amp.cfg), chaque {{...}} du modele a son reglage, et le lanceur
   attend exactement ces cles ; valeurs par defaut coherentes (bornes, enums, TeamKit) ;
4. aller-retour : on rend le modele comme AMP (remplacement brut), on passe le resultat
   dans le lanceur (le vrai code, importe), on encode en Latin-1, puis on relit le
   fichier comme le jeu (concatenation des lignes finies par \\, sequences \\n \\\\ \\",
   # qui n'est pas un commentaire apres un reglage texte). Vide, espaces, accents,
   virgules, #, {, ", barres obliques inverses, emojis, tiret long, codes couleur ;
5. les valeurs refusees le sont (nombre invalide, hors bornes, langue inconnue...) ;
6. le filtre de sortie, sur de vraies lignes du serveur 0.2.9.3.1 (relevees le
   10 oct. 2026 dans un conteneur jetable cubecoders/ampbase:debian, avec le vrai client
   0.2.9.3.1 sous Xvfb) : arrivee, depart, renommage, bruit retire, ligne « pret » ;
   et les regex de console d'AMP sur ce qu'il produit ;
7. les fichiers telecharges a l'Update existent dans scripts/, a l'URL du depot du
   manifest ; l'AppImage vient de l'URL stable officielle ;
8. fins de ligne LF, aucun {{ dans le lanceur, compilation Python ;
6 bis. cartes, modes, bots, votes (11/10/2026) : reglages TK_ identiques dans AMP, le
   modele et le lanceur ; un ancien formulaire (TK_ laisses tels quels ou vides) donne
   exactement le fonctionnement d'avant ; rotation dans l'ordre toutes les N manches,
   votes de mode et de carte, carte illisible, perso.cfg et bots renvoyes, remise a zero
   des reglages que les cartes fixent ; detection du vote sur de vraies lignes du serveur.
"""
import importlib.util
import io
import json
import os
import re
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
NOM = 'armagetron'
MODELE = 'scripts/AMP_reglages.cfg'
LANCEUR = 'scripts/lancer-armagetron.py'
APPIMAGE_URL = 'https://download.armagetronad.org/appimage/ArmagetronAdvancedDedicated.AppImage'
soucis = []


def lire(nom, binaire=False):
    chemin = os.path.join(ICI, nom)
    if binaire:
        with open(chemin, 'rb') as f:
            return f.read()
    with io.open(chemin, encoding='utf-8') as f:
        return f.read()


def py(motif):
    # AMP est en C# : (?<nom>...) ; Python veut (?P<nom>...)
    return re.compile(motif.replace('(?<', '(?P<'))


# ── 1. JSON ──────────────────────────────────────────────────────────────────
data = {}
for nom in ('manifest.json', NOM + 'config.json', NOM + 'metaconfig.json', NOM + 'ports.json', NOM + 'updates.json'):
    try:
        data[nom] = json.loads(lire(nom))
        print('ok   %-26s JSON valide' % nom)
    except Exception as e:
        soucis.append('%s : JSON invalide (%s)' % (nom, e))
if soucis:
    print('\n'.join('NON  ' + s for s in soucis))
    sys.exit(1)
config = data[NOM + 'config.json']
updates = data[NOM + 'updates.json']
ports = data[NOM + 'ports.json']

# ── 2. kvp ───────────────────────────────────────────────────────────────────
kvp = lire(NOM + '.kvp')
cles = dict(l.split('=', 1) for l in kvp.splitlines() if '=' in l)
for ref in re.findall(r'@IncludeJson\[([^\]]+)\]', kvp):
    if not os.path.isfile(os.path.join(ICI, ref)):
        soucis.append('@IncludeJson[%s] : fichier absent' % ref)
for cle in ('Meta.ConfigManifest', 'Meta.MetaConfigManifest'):
    if not os.path.isfile(os.path.join(ICI, cles.get(cle, '?'))):
        soucis.append('%s pointe sur un fichier absent' % cle)
refs = {p['Ref'] for p in ports}
if cles.get('App.PrimaryApplicationPortRef') not in refs:
    soucis.append('PrimaryApplicationPortRef ne correspond a aucun port')
if any(p['Protocol'] != 'UDP' for p in ports):
    soucis.append('Armagetron n\'utilise que l\'UDP')
cmd = cles.get('App.CommandLineArgs', '')
for r in re.findall(r'\{\{\$(\w+)\}\}', cmd):
    if r not in refs and r not in ('FullBaseDir', 'MaxUsers'):
        soucis.append('{{$%s}} : aucun port ne porte ce Ref' % r)
if cmd != '-u "{{$FullBaseDir}}lancer-armagetron.py" lancer {{$%s}} {{$MaxUsers}}' % cles.get('App.PrimaryApplicationPortRef'):
    soucis.append('ligne de commande inattendue : %s' % cmd)
if cles.get('App.ExecutableLinux') != '/usr/bin/python3' or 'python3' not in json.loads(cles.get('Meta.ExtraContainerPackages', '[]')):
    soucis.append('le lanceur est en Python : ExecutableLinux=/usr/bin/python3 et python3 dans ExtraContainerPackages')
print('ok   ports                      %s' % ', '.join('%s %s/%s' % (p['Ref'], p['Port'], p['Protocol']) for p in ports))
ATTENDUES = ['App.SupportsUniversalSleep', 'App.WakeupMode', 'App.ApplicationReadyMode', 'Console.FilterMatchRegex', 'Console.FilterMatchReplacement', 'Console.ThrowawayMessageRegex', 'Console.AppReadyRegex', 'Console.UserJoinRegex', 'Console.UserLeaveRegex', 'Console.UserChatRegex', 'Console.UpdateAvailableRegex', 'Console.PreConnectRegex', 'Console.ConnectIPRegex', 'Console.MetricsRegex', 'Console.HideFromConsoleRegex', 'Console.SuppressLogAtStart', 'Console.UserActions', 'Limits.SleepMode', 'Limits.SleepOnStart', 'Limits.SleepDelayMinutes', 'Limits.DozeDelay', 'Limits.AutoRetryCount', 'Limits.SleepStartThresholdSeconds']
absentes = [c for c in ATTENDUES if c not in cles]
if absentes:
    soucis.append('cles absentes du .kvp : ' + ', '.join(absentes))
else:
    print('ok   kvp complet                les %d cles Console/Limits sont la' % len(ATTENDUES))
if cles.get('App.ApplicationReadyMode') == 'RegexMatch' and not cles.get('Console.AppReadyRegex'):
    soucis.append('RegexMatch sans AppReadyRegex : l\'instance ne serait jamais declaree prete')
if cles.get('App.HasWriteableConsole') != 'True' or cles.get('App.AdminMethod') != 'STDIO':
    soucis.append('la console d\'AMP doit ecrire dans le lanceur (HasWriteableConsole=True, AdminMethod=STDIO)')
if cles.get('App.ExitMethod') != 'SIGTERM':
    soucis.append('App.ExitMethod doit etre SIGTERM : le lanceur le traduit en QUIT')
if cles.get('Meta.URL') != data['manifest.json']['url']:
    soucis.append('Meta.URL et manifest.json ne designent pas le meme depot')
if re.search(r'[^\x00-\x7f]', kvp):
    soucis.append('caractere non ASCII dans le .kvp')

# ── 3. reglages <-> modele <-> lanceur ──────────────────────────────────────
modele = lire(MODELE)
dans_modele = re.findall(r'\{\{([A-Za-z0-9_$]+)\}\}', modele)
params = {}
for c in config:
    p = c.get('ParamFieldName')
    if p in params:
        soucis.append('reglage en double : %s' % p)
    params[p] = c
    if c.get('IncludeInCommandLine') is not False:
        soucis.append('%s : IncludeInCommandLine doit etre false (AMP l\'ajouterait a la ligne de commande)' % p)
    if c['FieldName'] == '$MaxUsers':
        if p in dans_modele:
            soucis.append('MAX_CLIENTS passe par la ligne de commande, pas par le modele')
        continue
    if c['FieldName'] != p:
        soucis.append('%s : FieldName et ParamFieldName differents (%s)' % (p, c['FieldName']))
    if dans_modele.count(p) != 1:
        soucis.append('{{%s}} doit apparaitre une fois dans %s' % (p, MODELE))
    elif '%s {{%s}}' % (p, p) not in modele.splitlines():
        soucis.append('la ligne du modele pour %s doit etre « %s {{%s}} »' % (p, p, p))
    d = str(c.get('DefaultValue', ''))
    if c['InputType'] == 'number' and not (re.fullmatch(r'-?\d+', d) and int(c['MinValue']) <= int(d) <= int(c['MaxValue'])):
        soucis.append('%s : valeur par defaut %r hors bornes' % (p, d))
    if c['InputType'] == 'enum' and d not in c['EnumValues']:
        soucis.append('%s : valeur par defaut %r absente de la liste' % (p, d))
    if c['InputType'] == 'checkbox' and (d not in ('0', '1') or c['EnumValues'] != {'False': '0', 'True': '1'}):
        soucis.append('%s : case a cocher mal decrite' % p)
orphelins = set(dans_modele) - set(params)
if orphelins:
    soucis.append('{{...}} sans reglage dans AMP : %s' % ', '.join(sorted(orphelins)))
if not any(c['FieldName'] == '$MaxUsers' and c['MaxValue'] == '32' for c in config):
    soucis.append('il faut un reglage $MaxUsers limite a 32 (MAXCLIENTS du serveur dedie)')
if cles.get('App.MaxUsers') != [c['DefaultValue'] for c in config if c['FieldName'] == '$MaxUsers'][0]:
    soucis.append('App.MaxUsers et le defaut du reglage $MaxUsers different')
meta = data[NOM + 'metaconfig.json'][0]
racine = cles['App.RootDir'].strip('./').strip('/')
if meta.get('ConfigType') != 'template' or meta.get('ConfigFileTemplate') != racine + '/AMP_reglages.cfg':
    soucis.append('metaconfig : ConfigFileTemplate devrait etre %s/AMP_reglages.cfg' % racine)

spec = importlib.util.spec_from_file_location('lanceur', os.path.join(ICI, LANCEUR))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)
if meta.get('ConfigFile') != os.path.basename(L.REGLAGES_AMP):
    soucis.append('le fichier rendu par AMP (ConfigFile) n\'est pas celui que lit le lanceur')
enum_langues = set(params['LANGUAGE_FIRST']['EnumValues'])
if enum_langues != set(L.LANGUES):
    soucis.append('langues d\'AMP et du lanceur differentes : %s' % (enum_langues ^ set(L.LANGUES)))
d = params['MESSAGE_OF_DAY']['DefaultValue']
if 'TeamKit.fr' not in d or 'discord.gg/EuAjGMYPHY' not in d:
    soucis.append('le message d\'accueil par defaut doit citer TeamKit.fr et le Discord')
if 'TeamKit' not in params['SERVER_NAME']['DefaultValue']:
    soucis.append('le nom par defaut doit contenir TeamKit')
print('ok   correspondance             %d reglages, modele et lanceur d\'accord' % len(params))


# ── 4. aller-retour AMP -> lanceur -> lecture par le jeu ────────────────────
def rendre(valeurs):
    t = modele
    for p, v in valeurs.items():
        t = t.replace('{{%s}}' % p, v)
    return t


def echappement(s, i):
    """tString.cpp st_ReadEscapeSequence : s[i] == '\\'. Renvoie (texte, i suivant)."""
    if i + 1 >= len(s):
        return '\\', i + 1
    c = s[i + 1]
    if c == 'n':
        return '\n', i + 2
    if c in '" \'\\\n':
        return c, i + 2
    return '\\' + c, i + 2


def lire_ligne(reste):
    """tConfItemLine::ReadVal : tString::ReadLine(s, true)."""
    reste = reste.lstrip(' \t')
    sortie, i = [], 0
    while i < len(reste):
        if reste[i] == '\\':
            t, i = echappement(reste, i)
            sortie.append(t)
        else:
            sortie.append(reste[i])
            i += 1
    return ''.join(sortie)


def lire_mot(reste):
    """operator>>(istream, tString) : un mot, ou une chaine entre guillemets."""
    reste = reste.lstrip()
    if not reste:
        return ''
    guillemet = reste[0] if reste[0] in '"\'' else None
    i = 1 if guillemet else 0
    sortie = []
    while i < len(reste):
        c = reste[i]
        if c == '\\':
            t, i = echappement(reste, i)
            sortie.append(t)
            continue
        if guillemet and c == guillemet:
            break
        if not guillemet and c in ' \t':
            break
        sortie.append(c)
        i += 1
    return ''.join(sortie)


LIGNES_TEXTE = {'SERVER_NAME', 'SERVER_OPTIONS', 'TITLE_OF_DAY', 'MESSAGE_OF_DAY', 'LANGUAGE_FIRST'}


def lire_comme_le_jeu(octets):
    """tConfItemBase::LoadAll puis LoadLine, sur le fichier en Latin-1."""
    lignes = octets.decode('latin-1').split('\n')
    valeurs, i = {}, 0
    while i < len(lignes):
        ligne = lignes[i]
        i += 1
        while ligne.endswith('\\') and i < len(lignes):
            ligne = ligne[:-1]
            if ligne.endswith('\\'):
                break
            ligne += lignes[i]
            i += 1
        mots = ligne.split(None, 1)
        if not mots or mots[0].startswith('#'):
            continue
        cle = mots[0].upper()
        reste = ligne.lstrip()[len(mots[0]):]
        if cle in LIGNES_TEXTE:
            valeurs[cle] = lire_ligne(reste)
        elif cle == 'URL':
            valeurs[cle] = lire_mot(reste)
        else:
            valeurs[cle] = reste.split('#')[0].split()[0] if reste.split() else ''
    return valeurs


defauts = {p: str(c.get('DefaultValue', '')) for p, c in params.items()}
EMOJI = '\U0001F1EB\U0001F1F7'          # drapeau francais
ESSAIS = [
    # (reglage, valeur dans AMP, valeur attendue par le jeu)
    ('SERVER_NAME', defauts['SERVER_NAME'], defauts['SERVER_NAME']),
    ('SERVER_NAME', EMOJI + ' TeamKit \u00b7 FR', 'TeamKit \u00b7 FR'),
    ('SERVER_NAME', 'Serveur \u2014 \u00ab TeamKit \u00bb # 1 {a} "b" \u2019c\u2019 \u0153uvre', 'Serveur - \u00ab TeamKit \u00bb # 1 {a} "b" \'c\' oeuvre'),
    ('SERVER_NAME', 'Barre \\ oblique \\', 'Barre \\ oblique \\'),
    ('SERVER_NAME', 'pas de \\n ici', 'pas de \\n ici'),
    ('SERVER_NAME', '', 'TeamKit'),
    ('SERVER_NAME', EMOJI, 'TeamKit'),
    ('SERVER_NAME', '   espaces autour   ', 'espaces autour'),
    ('SERVER_OPTIONS', 'R\u00e8gles : fair-play, pas d\'insultes ; 100 % fun # ok', 'R\u00e8gles : fair-play, pas d\'insultes ; 100 % fun # ok'),
    ('SERVER_OPTIONS', '', ''),
    ('TITLE_OF_DAY', 'Bienvenue \u00e0 tous !', 'Bienvenue \u00e0 tous !'),
    ('MESSAGE_OF_DAY', defauts['MESSAGE_OF_DAY'], defauts['MESSAGE_OF_DAY'].replace('\\n', '\n')),
    ('MESSAGE_OF_DAY', 'Ligne 1\\nLigne 2 # pas un commentaire {x} "y" C:\\temp\\', 'Ligne 1\nLigne 2 # pas un commentaire {x} "y" C:\\temp\\'),
    ('MESSAGE_OF_DAY', 'fin en double \\\\', 'fin en double \\'),
    ('MESSAGE_OF_DAY', '', ''),
    ('URL', 'https://teamkit.fr', 'https://teamkit.fr'),
    ('URL', 'https://team kit.fr', 'https://teamkit.fr'),
    ('URL', '', ''),
    ('LANGUAGE_FIRST', 'Polish (bez znakow specjalnych)', 'Polish (bez znakow specjalnych)'),
    ('TALK_TO_MASTER', '0', '0'),
    ('SPEED_FACTOR', '-2', '-2'),
    ('MIN_PLAYERS', '16', '16'),
]
n = 0
for p, v, attendu in ESSAIS:
    vals = dict(defauts)
    vals[p] = v
    avis = []
    try:
        contenu = L.construire(rendre(vals), L.PERSO_MODELE, 4534, 16, avis.append)
        octets = contenu.encode('latin-1')
    except Exception as e:
        soucis.append('aller-retour %s=%r : %s' % (p, v, e))
        continue
    lu = lire_comme_le_jeu(octets)
    n += 1
    if lu.get(p) != attendu:
        soucis.append('aller-retour %s : ecrit %r, le jeu lit %r (attendu %r)' % (p, v, lu.get(p), attendu))
    if EMOJI in v and not any('retires' in a for a in avis):
        soucis.append('emoji retire sans le dire dans la console : %r' % v)
    if lu.get('SERVER_PORT') != '4534' or lu.get('MAX_CLIENTS') != '16' or lu.get('CONSOLE_LADDER_LOG') != '1':
        soucis.append('lignes imposees absentes ou ecrasees')
    autres = {k: x for k, x in lu.items() if k != p}
    if p != 'SERVER_NAME' and autres.get('SERVER_NAME') != defauts['SERVER_NAME']:
        soucis.append('%s=%r deborde sur les autres reglages' % (p, v))
# perso.cfg passe apres AMP, et les lignes imposees apres perso.cfg
contenu = L.construire(rendre(defauts), 'SERVER_NAME Autre nom \u00e9\nSERVER_PORT 9999\nWALLS_LENGTH 300\n', 4534, 16, lambda m: None)
lu = lire_comme_le_jeu(contenu.encode('latin-1'))
if lu['SERVER_NAME'] != 'Autre nom \u00e9' or lu['SERVER_PORT'] != '4534' or lu.get('WALLS_LENGTH') != '300':
    soucis.append('ordre AMP < perso.cfg < lignes imposees non respecte : %r' % lu)
n += 1
# une valeur qui deborde sur une deuxieme ligne est signalee
avis = []
L.construire(rendre(dict(defauts, MESSAGE_OF_DAY='a\nINTRUS 1')), '', 4534, 16, avis.append)
if not any('ignoree' in a for a in avis):
    soucis.append('une ligne inattendue dans reglages-amp.cfg doit etre signalee')
print('ok   aller-retour               %d valeurs (vide, accents, #, {, ", \\, emoji, tiret long, couleurs, \\n)' % n)

# ── 5. refus ─────────────────────────────────────────────────────────────────
REFUS = [('LIMIT_ROUNDS', 'dix'), ('LIMIT_ROUNDS', '0'), ('MIN_PLAYERS', '-1'), ('TEAM_MAX_PLAYERS', '99'),
         ('SPEED_FACTOR', '1.5'), ('SIZE_FACTOR', ''), ('TALK_TO_MASTER', 'True'),
         ('LANGUAGE_FIRST', 'Fran\u00e7ais'), ('URL', '"https://teamkit.fr"')]
for p, v in REFUS:
    try:
        L.construire(rendre(dict(defauts, **{p: v})), '', 4534, 16, lambda m: None)
        soucis.append('%s=%r aurait du etre refuse' % (p, v))
    except L.Refus:
        pass
print('ok   refus                      %d valeurs invalides refusees avec un message' % len(REFUS))

# ── 6. filtre de sortie et regex de console (lignes reelles, 10/10/2026) ─────
f = L.Filtre(4534)
SEQUENCE = [
    ('[L] ENCODING latin1', []),
    ('[0] Bound socket to *.*.*.*:36896.', ['[0] Bound socket to *.*.*.*:36896.']),
    ('[0] Bound socket to *.*.*.*:4534.', ['[0] Bound socket to *.*.*.*:4534.', 'TeamKit : Armagetron Advanced pret sur le port 4534 (UDP).']),
    ('[0] Personne ici. Faites un petit somme...', ['[0] Personne ici. Faites un petit somme...']),
    ('[0] Bound socket to *.*.*.*:4534.', ['[0] Bound socket to *.*.*.*:4534.']),   # pas une 2e ligne « pret »
    ('[33] Answering ping poll from 172.17.0.30:41661.', []),
    ('[1] Login recu de 172.17.0.30:55711.', ['[1] Login recu de 172.17.0.30:55711.']),
    ('[0] En attente de joueurs reels...', []),
    ('[0] En attente de joueurs reels ( seuls des spectateurs sont en ligne )...', []),
    ('[0] Waiting for real players...', []),
    ('[0] ', []),
    ('[0] Command HUD_CACHE_THRESHOLD unknown.', []),
    ('[L] PLAYER_ENTERED essai 172.17.0.30 essai', ['TeamKit : arrivee de essai']),
    ('[L] TEAM_CREATED essai', []),
    ('[1] essai est entre(e) dans le jeu.', ['[1] essai est entre(e) dans le jeu.']),
    ('[1] essai: salut', ['[1] essai: salut']),
    ('[0] Ping change de 100 a 0.', []),
    ('[L] PLAYER_RENAMED essai kevin_te 172.17.0.30 K\u00e9vin T\u00e9', ['TeamKit : depart de essai', 'TeamKit : arrivee de K\u00e9vin T\u00e9']),
    ('[0] essai has been renamed to K\u00e9vin T\u00e9.', ['[0] essai has been renamed to K\u00e9vin T\u00e9.']),
    ('[L] PLAYER_ENTERED zorg 203.0.113.9 0xff0000Zo0xffffffrg', ['TeamKit : arrivee de Zorg']),
    ('[L] PLAYER_LEFT kevin_te 172.17.0.30', ['TeamKit : depart de K\u00e9vin T\u00e9']),
    ('[L] PLAYER_LEFT zorg 203.0.113.9', ['TeamKit : depart de Zorg']),
    ('[L] PLAYER_LEFT inconnu 203.0.113.9', ['TeamKit : depart de inconnu']),
    ('TeamKit : arrivee de Faux', [' TeamKit : arrivee de Faux']),
    ('Envoyes:   9034 octets dans 47 paquets (44.4856 octets/s)', ['Envoyes:   9034 octets dans 47 paquets (44.4856 octets/s)']),
    ('[0] Admin: Bonjour \u00e0 tous', ['[0] Admin: Bonjour \u00e0 tous']),
]
sorties = []
for entree, attendu in SEQUENCE:
    s = f.ligne(entree)
    sorties += s
    if s != attendu:
        soucis.append('filtre : %r donne %r au lieu de %r' % (entree, s, attendu))
joins = [m.group('username') for l in sorties for m in [py(cles['Console.UserJoinRegex']).search(l)] if m]
leaves = [m.group('username') for l in sorties for m in [py(cles['Console.UserLeaveRegex']).search(l)] if m]
prets = [l for l in sorties if py(cles['Console.AppReadyRegex']).search(l)]
if joins != ['essai', 'K\u00e9vin T\u00e9', 'Zorg'] or leaves != ['essai', 'K\u00e9vin T\u00e9', 'Zorg', 'inconnu'] or len(prets) != 1:
    soucis.append('regex de console : arrivees %r, departs %r, pret %r' % (joins, leaves, prets))
PIEGES = [
    ('Console.UserJoinRegex', '[1] essai est entre(e) dans le jeu.'),
    ('Console.UserJoinRegex', ' TeamKit : arrivee de Faux'),
    ('Console.UserLeaveRegex', '[1] essai quitte le jeu.'),
    ('Console.UserLeaveRegex', 'TeamKit : arrivee de essai'),
    ('Console.AppReadyRegex', '[0] Bound socket to *.*.*.*:4534.'),
]
for cle, ligne in PIEGES:
    if py(cles[cle]).search(ligne):
        soucis.append('%s attrape une ligne qui n\'est pas pour lui : %r' % (cle, ligne))
# Latin-1 -> affichable : conversion de la console d'AMP vers le serveur
t, retires = L.vers_latin1('SAY Bonjour \u00e0 tous \u2014 c\u2019est TeamKit \U0001F600')
if t != 'SAY Bonjour \u00e0 tous - c\'est TeamKit ' or retires != ['\U0001F600']:
    soucis.append('vers_latin1 : %r %r' % (t, retires))
print('ok   console                    %d lignes reelles, %d pieges' % (len(SEQUENCE), len(PIEGES)))

# ── 6 bis. cartes, modes, bots, votes (11/10/2026) ──────────────────────────
import random as _random

nouvelles = set(L.NOUVELLES)
dans_json = {c['ParamFieldName'] for c in config if c['ParamFieldName'].startswith('TK_')}
if nouvelles != dans_json:
    soucis.append('reglages TK_ : lanceur et AMP differents : %s' % sorted(nouvelles ^ dans_json))
if not nouvelles <= set(dans_modele):
    soucis.append('reglages TK_ absents du modele : %s' % sorted(nouvelles - set(dans_modele)))
if set(L.MODES) & set(L.CARTES):
    soucis.append('un mode et une carte portent le meme nom : %s' % (set(L.MODES) & set(L.CARTES)))
for nom, (chemin, typ, equipes, libelle) in L.CARTES.items():
    if not L.NOM_VOTE.fullmatch(nom) or not L.CHEMIN_CARTE.fullmatch(chemin) or typ not in L.SECOURS:
        soucis.append('carte %s mal decrite' % nom)
    if typ == 'forteresse' and equipes not in (2, 4):
        soucis.append('carte %s : nombre d\'equipes inattendu' % nom)
    try:
        libelle.encode('latin-1')
    except UnicodeEncodeError:
        soucis.append('libelle hors Latin-1 : %s' % libelle)
for m, (libelle, typ, regles) in L.MODES.items():
    if typ not in L.SECOURS or not set(regles) <= set(L.BASE):
        soucis.append('mode %s : type ou reglage inconnu (%s)' % (m, set(regles) - set(L.BASE)))
if set(params['TK_MODE']['EnumValues']) != set(L.MODES):
    soucis.append('modes d\'AMP et du lanceur differents')
if set(params['TK_ROTATION']['EnumValues']) != set(L.ROTATIONS) or set(params['TK_VOTES']['EnumValues']) != set(L.VOTES):
    soucis.append('listes rotation / votes d\'AMP et du lanceur differentes')
for nom in re.split(r'[,\s]+', params['TK_CARTES']['DefaultValue'].strip()):
    if nom not in L.CARTES:
        soucis.append('carte par defaut inconnue : %s' % nom)
for nom in L.CARTES:
    if nom not in params['TK_CARTES']['Description']:
        soucis.append('carte %s absente de la description d\'AMP' % nom)

# formulaire d'avant le 11/10 : AMP laisse {{TK_...}} ou n'ecrit rien -> fonctionnement d'avant
for rendu in ('litteral', 'vide'):
    vals = {p: d for p, d in defauts.items() if not p.startswith('TK_')}
    t = rendre(vals)
    if rendu == 'vide':
        t = re.sub(r'\{\{TK_[A-Z_]+\}\}', '', t)
    avis = []
    try:
        contenu, rot, fichiers = L.preparer(t, '', 4534, 16, avis.append)
    except L.Refus as e:
        soucis.append('ancien formulaire (%s) refuse : %s' % (rendu, e))
        continue
    lu = lire_comme_le_jeu(contenu.encode('latin-1'))
    attendu = {'WAIT_FOR_EXTERNAL_SCRIPT': '0', 'MAP_FILE': 'Anonymous/polygon/regular/square-1.0.1.aamap.xml',
               'ALLOW_VOTING': '1', 'MIN_VOTERS': '3', 'VOTING_MATURITY': '300', 'SP_MIN_PLAYERS': '4',
               'NUM_AIS': '0', 'AI_IQ': '50', 'AUTO_AIS': '0', 'TEAM_MAX_PLAYERS': defauts['TEAM_MAX_PLAYERS']}
    for cle, v in L.BASE.items():
        if not v.startswith('@'):
            attendu[cle] = v
    ecarts = {k: (lu.get(k), v) for k, v in attendu.items() if lu.get(k) != v}
    if ecarts or rot is not None or fichiers or 'ACCESS_LEVEL_VOTE_INCLUDE' in lu:
        soucis.append('ancien formulaire (%s) : le fonctionnement change : %s' % (rendu, ecarts))
    if not any('absents du formulaire' in a for a in avis):
        soucis.append('ancien formulaire (%s) : pas de message dans la console' % rendu)

# nouveau formulaire, valeurs par defaut
contenu, rot, fichiers = L.preparer(rendre(defauts), 'WALLS_LENGTH 300\nAI_IQ 90\n', 4534, 16,
                                    lambda m: soucis.append('avertissement inattendu : ' + m),
                                    _random.Random(3))
lu = lire_comme_le_jeu(contenu.encode('latin-1'))
if rot is None or lu.get('WAIT_FOR_EXTERNAL_SCRIPT') != '1' or lu.get('ACCESS_LEVEL_VOTE_INCLUDE') != '20':
    soucis.append('defauts : rotation ou votes inactifs')
if lu.get('MIN_VOTERS') != str(int(defauts['TK_VOTES_JOUEURS']) - 1) or lu.get('WALLS_LENGTH') != '300':
    soucis.append('defauts : MIN_VOTERS ou perso.cfg mal appliques')
attendus = set()
for nom in list(L.MODES) + re.split(r'[,\s]+', defauts['TK_CARTES'].strip()):
    attendus |= {nom, nom + '.cfg'}
if set(fichiers) != attendus:
    soucis.append('fichiers de vote inattendus : %s' % sorted(set(fichiers) ^ attendus))
aide = [l for l in contenu.splitlines() if l.startswith('ADD_HELP_TOPIC votes ')]
if not aide or '/vote include' not in aide[0] or 'fortcarre' not in aide[0]:
    soucis.append('aide /help votes absente ou incomplete')

# rotation : ordre, toutes les N manches, votes, carte illisible, perso.cfg et bots renvoyes
cartes = L.lire_cartes('carre, diamant, fort2, fort4, sumo4, Auteur/x/ma_carte-1.0.aamap.xml, '
                       'forteresse:Auteur/y/fort-2.aamap.xml, ../x.aamap.xml, inconnue', lambda m: None)
noms = [c[0] for c in cartes]
if noms != ['carre', 'diamant', 'fort2', 'fort4', 'sumo4', 'ma_carte', 'fort'] or cartes[6][2:4] != ('forteresse', 2):
    soucis.append('lecture de la liste de cartes : %s' % noms)
r = L.Rotation('classique', cartes, 'ordre', 2, {'TEAM_MAX_PLAYERS': '5', 'SIZE_FACTOR': '0'},
               {'WALLS_LENGTH': '300'}, _random.Random(1), ['NUM_AIS 2', 'SP_MIN_PLAYERS 4'])
suite = []
for _ in range(6):
    cmds = r.fin_de_manche()
    suite.append(r.carte[0])
    if cmds[-1] != 'WAIT_FOR_EXTERNAL_SCRIPT 0':
        soucis.append('fin de manche sans WAIT_FOR_EXTERNAL_SCRIPT 0')
if suite != ['carre', 'diamant', 'diamant', 'ma_carte', 'ma_carte', 'carre']:
    soucis.append('rotation dans l\'ordre toutes les 2 manches : %s' % suite)
r.vote('forteresse')
cmds = dict(c.split(' ', 1) for c in r.fin_de_manche() if not c.startswith('CONSOLE'))
if r.mode != 'forteresse' or r.carte[0] != 'fort2' or cmds.get('TEAMS_MAX') != '2' or cmds.get('TEAM_MAX_PLAYERS') != '5':
    soucis.append('vote de mode forteresse : %s %s %s' % (r.mode, r.carte[0], cmds.get('TEAMS_MAX')))
if cmds.get('WALLS_LENGTH') != '300' or cmds.get('NUM_AIS') != '2' or cmds.get('SP_TEAMS_MIN') != '1':
    soucis.append('perso.cfg, bots ou remise a zero des reglages de carte non renvoyes : %s' % cmds)
r.vote('sumo4')
r.fin_de_manche()
if (r.mode, r.carte[0]) != ('sumo', 'sumo4'):
    soucis.append('vote de carte sumo : %s %s' % (r.mode, r.carte[0]))
r.vote('carre')
r.fin_de_manche()
if (r.mode, r.carte[0]) != ('classique', 'carre'):
    soucis.append('vote de carte classique depuis le sumo : %s %s' % (r.mode, r.carte[0]))
r.vote('diamant')
r.fin_de_manche()
r.carte_ratee()
if r.carte[0] != 'carre' or 'Anonymous/polygon/regular/diamond-1.0.2.aamap.xml' not in r.ratees:
    soucis.append('carte illisible : retour a la precedente rate')
if r.vote('inconnue') is not None:
    soucis.append('vote d\'un nom inconnu accepte')

# filtre : votes, echo des reglages, attente entre manches
f = L.Filtre(4534, L.Rotation('classique', cartes, 'aleatoire', 1, {'TEAM_MAX_PLAYERS': '5', 'SIZE_FACTOR': '0'}, {}, _random.Random(2)))
VOTES_REELS = [
    ('[1] Including file vote/forteresse. Only users of access level Moderator or higher will receive the output.', 'forteresse'),
    ('[2] Including file vote/hexatron.cfg. Only users of access level Moderator or higher will receive the output.', None),
    ('[2] Including file vote/fort4.cfg. Only users of access level Moderator or higher will receive the output.', 'fort4'),
    ('[1] Player 1: Including file vote/sumo.', None),
    ('[1] Sondage "Include forteresse" accepte.', None),
    ('[1] Include file vote/../perso.cfg not found or not readable.', None),
]
for ligne, attendu in VOTES_REELS:
    f.rotation.vote_mode = f.rotation.vote_carte = None
    sortie = f.ligne(ligne)
    vu = f.rotation.vote_mode or (f.rotation.vote_carte or (None,))[0]
    if vu != attendu or sortie[0] != ligne:
        soucis.append('detection de vote : %r -> %r' % (ligne, vu))
for ligne in ('[0] MAP_FILE a change A en B.', '[0] Setting MAP_FILE (Group: Breaking) deviates from its default value; clients older than 0.2.8_beta3 will not be allowed in.',
              '[0] WAIT_FOR_EXTERNAL_SCRIPT a change 1 en 0.', '[0] SP_TEAMS_MIN a change 1 en 2.', '[0] FORTRESS_MAX_PER_TEAM a change 0 en 2.'):
    if f.ligne(ligne):
        soucis.append('echo de reglage non filtre : %r' % ligne)
f.ligne('[L] WAIT_FOR_EXTERNAL_SCRIPT')
if not f.a_envoyer or f.a_envoyer[-1] != 'WAIT_FOR_EXTERNAL_SCRIPT 0':
    soucis.append('evenement WAIT_FOR_EXTERNAL_SCRIPT sans reponse')
f.a_envoyer = []
f.ligne('[L] NEW_ROUND 2026-10-11 09:56:50 UTC')
if f.a_envoyer != ['WAIT_FOR_EXTERNAL_SCRIPT 1']:
    soucis.append('NEW_ROUND doit remettre WAIT_FOR_EXTERNAL_SCRIPT 1')
if not f.ligne('[0] The map TeamKit/essai/inexistante-1.0.aamap.xml could not be loaded or parsed; please check your configuration and the log.')[1:]:
    soucis.append('carte illisible non signalee')
print('ok   cartes, modes, votes       %d cartes, %d modes, ancien formulaire inchange, rotation simulee' % (len(L.CARTES), len(L.MODES)))

# ── 7. fichiers telecharges a l'Update ───────────────────────────────────────
depot = data['manifest.json']['url'].replace('https://github.com/', '')
fetch = [e for e in updates if e['UpdateSource'] == 'FetchURL']
for e in fetch:
    if e['UpdateSourceArgs'].endswith('.AppImage'):
        if e['UpdateSourceData'] != APPIMAGE_URL or e['UpdateSourceArgs'] != os.path.basename(L.APPIMAGE):
            soucis.append('AppImage : URL ou nom inattendu (%s)' % e['UpdateSourceData'])
        continue
    attendu = 'https://raw.githubusercontent.com/%s/main/scripts/%s' % (depot, e['UpdateSourceArgs'])
    if e['UpdateSourceData'] != attendu:
        soucis.append('URL inattendue pour %s : %s' % (e['UpdateSourceArgs'], e['UpdateSourceData']))
    elif not os.path.isfile(os.path.join(ICI, 'scripts', e['UpdateSourceArgs'])):
        soucis.append('scripts/%s absent du depot' % e['UpdateSourceArgs'])
    else:
        print('ok   telecharge a l\'Update      scripts/%s' % e['UpdateSourceArgs'])
if {e['UpdateSourceArgs'] for e in fetch} != {'ArmagetronAdvancedDedicated.AppImage', 'AMP_reglages.cfg', 'lancer-armagetron.py'}:
    soucis.append('l\'Update doit deposer l\'AppImage, AMP_reglages.cfg et lancer-armagetron.py')
dernier = updates[-1]
if dernier['UpdateSource'] != 'Executable' or 'lancer-armagetron.py\\" installer' not in json.dumps(dernier['UpdateSourceArgs']):
    soucis.append('la derniere etape de l\'Update doit lancer « lancer-armagetron.py installer »')

# ── 8. fichiers ──────────────────────────────────────────────────────────────
for nom in (LANCEUR, MODELE):
    if b'\r' in lire(nom, binaire=True):
        soucis.append('%s : fins de ligne Windows (CRLF)' % nom)
if '{{' in lire(LANCEUR):
    soucis.append('le lanceur contient {{ : AMP pourrait le remplacer')
try:
    compile(lire(LANCEUR), LANCEUR, 'exec')
    print('ok   compilation                %s' % LANCEUR)
except SyntaxError as e:
    soucis.append('%s : %s' % (LANCEUR, e))

print()
if soucis:
    print('%d probleme(s) :' % len(soucis))
    print('\n'.join('  NON  ' + s for s in soucis))
    sys.exit(1)
print('Tout est bon.')
