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
            6. a l'arret demande par AMP (SIGTERM), envoie QUIT au serveur ;
            7. entre deux manches (evenement WAIT_FOR_EXTERNAL_SCRIPT), change de carte
               et de mode : rotation et votes /vote include <nom> (voir plus bas).
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


ANCIENNES = ('SERVER_NAME', 'TALK_TO_MASTER', 'SERVER_OPTIONS', 'URL', 'TITLE_OF_DAY',
             'MESSAGE_OF_DAY', 'LANGUAGE_FIRST', 'LIMIT_ROUNDS', 'MIN_PLAYERS',
             'TEAM_MAX_PLAYERS', 'SPEED_FACTOR', 'SIZE_FACTOR')

# Reglages ajoutes le 11/10/2026. Une instance creee avant garde son ancien formulaire
# (Fetch Latest ne le remplace pas) : AMP laisse alors le repere TK_... entre accolades ou n'ecrit
# rien. Chaque reglage absent prend la valeur ci-dessous, qui reproduit EXACTEMENT
# le fonctionnement d'avant (mode du jeu par defaut, pas de rotation, votes d'origine).
NOUVELLES = {
    'TK_MODE': 'equipes',
    'TK_CARTES': 'carre',
    'TK_ROTATION': 'aucune',
    'TK_ROTATION_MANCHES': '1',
    'TK_BOTS': '1',
    'TK_BOTS_PERMANENTS': '0',
    'TK_BOTS_NIVEAU': '50',
    'TK_BOTS_ADAPTATIFS': '0',
    'TK_VOTES': 'exclusion',
    'TK_VOTES_JOUEURS': '4',
    'TK_VOTES_ANCIENNETE': '300',
    'TK_VOTES_MODES': 'classique, equipes, forteresse, zone, sumo',
}


def lire_cles(texte, avertir):
    """reglages-amp.cfg -> {cle: valeur brute}. Les anciennes cles sont obligatoires."""
    vus = {}
    for brute in texte.splitlines():
        ligne = brute.rstrip('\r')
        if not ligne.strip() or ligne.lstrip().startswith('#'):
            continue
        cle, _, valeur = ligne.partition(' ')
        if (cle in ANCIENNES or cle in NOUVELLES) and cle not in vus:
            vus[cle] = valeur
        else:
            # une valeur contenant un vrai retour a la ligne deborde sur la ligne suivante
            avertir('reglages-amp.cfg : ligne ignoree : %s' % ligne[:80])
    manque = [c for c in ANCIENNES if c not in vus]
    if manque:
        raise Refus('reglages-amp.cfg incomplet (%s) : lance Update pour reprendre le modele.'
                    % ', '.join(manque))
    absentes = []
    for cle, defaut in NOUVELLES.items():
        v = vus.get(cle)
        if v is None or not v.strip() or re.fullmatch(r'\s*\{\{[^}]*\}\}\s*', v):
            vus[cle] = defaut
            absentes.append(cle)
    if absentes:
        avertir('%d reglage(s) des cartes, modes, bots et votes absents du formulaire AMP de '
                'cette instance : valeurs d\'avant utilisees (voir le README pour mettre le '
                'formulaire a jour).' % len(absentes))
    return vus


def lire_reglages_amp(texte, avertir):
    """Lit reglages-amp.cfg (rendu par AMP) et renvoie les lignes du jeu, controlees."""
    vus = lire_cles(texte, avertir)
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


# ── cartes, modes de jeu, bots, votes (11/10/2026) ──────────────────────────
#
# La version officielle 0.2.9.3.1 n'a PAS de rotation de cartes (aucun MAP_ROTATION
# dans le code). Ce lanceur la fait lui-meme avec le mecanisme prevu pour les scripts :
# WAIT_FOR_EXTERNAL_SCRIPT 1 -> a la fin de chaque manche, le serveur ecrit l'evenement
# WAIT_FOR_EXTERNAL_SCRIPT et attend (3 s au plus) qu'on remette le reglage a 0 ; le
# lanceur envoie alors MAP_FILE et les reglages du mode, pris en compte a la creation
# de la grille suivante (gGame.cpp, GS_PLAY -> GS_TRANSFER_SETTINGS -> GS_CREATE_GRID).

# nom court (vote, liste AMP) : (chemin dans le depot de ressources, type, equipes, libelle)
# Types : 'classique' (pas de zone), 'forteresse' (une zone a defendre par equipe),
# 'sumo' (une zone par joueur). « equipes » = nombre de points d'apparition = d'equipes.
# Les 10 premieres viennent avec le jeu (dossier resource/included, rien a telecharger) ;
# les autres sont sur resource.armagetronad.net, telechargees par le serveur et par
# chaque joueur la premiere fois (toutes essayees le 11/10/2026 avec le vrai client).
CARTES = {
    'carre': ('Anonymous/polygon/regular/square-1.0.1.aamap.xml', 'classique', 0, 'Carré'),
    'diamant': ('Anonymous/polygon/regular/diamond-1.0.2.aamap.xml', 'classique', 0, 'Diamant'),
    'polygone': ('Anonymous/polygon/regular/40-gon-0.2.aamap.xml', 'classique', 0, 'Polygone à 40 côtés'),
    'inaktek': ('Your_mom/clever/inaktek-0.7.2.aamap.xml', 'classique', 0, 'Inaktek'),
    'repeat': ('Your_mom/clever/repeat-0.3.2.aamap.xml', 'classique', 0, 'Repeat'),
    'fort2': ('Z-Man/fortress/for_old_clients-0.1.0.aamap.xml', 'forteresse', 2, 'Forteresse à 2 camps'),
    'fort4': ('Z-Man/fortress/fourfold_for_old_clients-0.1.0.aamap.xml', 'forteresse', 4, 'Forteresse à 4 camps'),
    'sumo4': ('Z-Man/fortress/sumo_4x4-0.1.1.aamap.xml', 'sumo', 16, 'Sumo 4x4'),
    'hexatron': ('Luke-Jr/Classic/HexaTRON-0.4.3.aamap.xml', 'classique', 0, 'HexaTRON'),
    'croix': ('Your_mom/clever/ironcross-0.8.3.aamap.xml', 'classique', 0, 'Croix de fer'),
    'tripath': ('Your_mom/clever/tripath-0.3.6.aamap.xml', 'classique', 0, 'Tripath'),
    'dents': ('Your_mom/clever/twoxdentedsquare-0.0.2.aamap.xml', 'classique', 0, 'Carré à dents'),
    'fortcarre': ('Luke-Jr/SoloFortress/Square-0.2.1.aamap.xml', 'forteresse', 4, 'Forteresse carrée'),
    'egalite': ('Luke-Jr/WildFortress/equal-0.3.1.aamap.xml', 'forteresse', 2, 'Égalité'),
    'fosse': ('Z-Man/fortress/pit_4x4-0.1.1.aamap.xml', 'sumo', 16, 'La fosse'),
}
# carte de secours par type, si la liste d'AMP n'en propose aucune pour le mode
SECOURS = {'classique': 'carre', 'forteresse': 'fort2', 'sumo': 'sumo4'}

# Valeurs par defaut du jeu pour tout reglage qu'un mode change (lues dans
# settings.cfg puis settings_dedicated.cfg de la 0.2.9.3.1 ; l'etape « installer »
# les recompare aux fichiers de la version installee). '@equipe' = « Joueurs par
# equipe » d'AMP, '@taille' = « Taille de l'arene » d'AMP, '@carte' = equipes de la carte.
BASE = {
    'TEAM_MAX_PLAYERS': '@equipe', 'TEAMS_MIN': '1', 'TEAMS_MAX': '16',
    'GAME_TYPE': '1', 'SP_GAME_TYPE': '1',
    'WIN_ZONE_DEATHS': '0', 'WIN_ZONE_MIN_ROUND_TIME': '60', 'WIN_ZONE_MIN_LAST_DEATH': '30',
    'WIN_ZONE_INITIAL_SIZE': '5', 'WIN_ZONE_EXPANSION': '1', 'WIN_ZONE_RANDOMNESS': '.8',
    'FORTRESS_CONQUEST_RATE': '.5', 'FORTRESS_DEFEND_RATE': '.25',
    'FORTRESS_CONQUEST_DECAY_RATE': '.1', 'FORTRESS_CONQUERED_SCORE': '0',
    'FORTRESS_CONQUERED_WIN': '0', 'FORTRESS_SURVIVE_WIN': '1',
    'FORTRESS_CONQUERED_KILL_MIN': '0', 'FORTRESS_CONQUERED_KILL_RATIO': '0.0',
    'FORTRESS_CONQUEST_TIMEOUT': '0',
    'SCORE_WIN': '10', 'SP_SCORE_WIN': '10', 'SCORE_KILL': '3', 'SCORE_SUICIDE': '-4',
    'SCORE_DIE': '-2', 'LIMIT_SCORE': '100',
    'WALLS_LENGTH': '-1', 'SP_WALLS_LENGTH': '-1', 'CYCLE_RUBBER': '1.0', 'CYCLE_ACCEL': '10.0',
    'EXPLOSION_RADIUS': '4', 'SP_EXPLOSION_RADIUS': '4', 'CYCLE_RUBBER_WALL_SHRINK': '0',
    'SIZE_FACTOR': '@taille', 'SP_SIZE_FACTOR': '-3',
    # Reglages que des cartes fixent elles-memes (balises <Setting> du fichier .aamap.xml,
    # vu le 11/10/2026 : fort2 met SP_MIN_PLAYERS 0, SP_TEAMS_MAX 2...). Ils RESTENT
    # apres la carte : on les remet a chaque changement de carte ou de mode.
    'SP_TEAMS_MIN': '1', 'SP_TEAMS_MAX': '16', 'FORTRESS_MAX_PER_TEAM': '0',
    'CYCLE_ACCEL_RIM': '0.0', 'SPAWN_POINT_GROUP_SIZE': '0', 'MAP_FILE_OVERRIDE': '3',
}
# Physique commune forteresse / sumo : config/examples/cvs_test/fortress_physics.cfg
_PHYSIQUE_FORT = {
    'CYCLE_RUBBER': '5', 'SP_EXPLOSION_RADIUS': '2', 'EXPLOSION_RADIUS': '2',
    'CYCLE_ACCEL': '20.0', 'SP_WALLS_LENGTH': '400', 'WALLS_LENGTH': '400',
    'CYCLE_RUBBER_WALL_SHRINK': '1',
}
# nom court : (libelle, type de carte, reglages qui changent par rapport a BASE)
MODES = {
    'classique': ('Classique (chacun pour soi)', 'classique', {'TEAM_MAX_PLAYERS': '1'}),
    # les regles du jeu sans rien changer (equipes formees automatiquement)
    'equipes': ('Équipes', 'classique', {}),
    # config/examples/fortress_soccer.cfg + cvs_test/fortress_physics.cfg + fortress_scoring.cfg
    # + les 3 lignes WIN_ZONE de cvs_test/fortress_complete.cfg ; une equipe par zone de la carte
    'forteresse': ('Forteresse', 'forteresse', dict(_PHYSIQUE_FORT, **{
        'TEAMS_MIN': '2', 'TEAMS_MAX': '@carte',
        'FORTRESS_CONQUEST_RATE': '.3', 'FORTRESS_DEFEND_RATE': '.2',
        'FORTRESS_CONQUEST_DECAY_RATE': '.1', 'FORTRESS_CONQUERED_SCORE': '0',
        'FORTRESS_CONQUERED_WIN': '0', 'FORTRESS_SURVIVE_WIN': '1',
        'FORTRESS_CONQUERED_KILL_MIN': '0', 'FORTRESS_CONQUERED_KILL_RATIO': '0',
        'GAME_TYPE': '1', 'SP_GAME_TYPE': '1', 'SCORE_WIN': '10', 'SP_SCORE_WIN': '10',
        'SCORE_SUICIDE': '0', 'SCORE_KILL': '2', 'SCORE_DIE': '0',
        'WIN_ZONE_RANDOMNESS': '.4', 'WIN_ZONE_MIN_ROUND_TIME': '120',
        'WIN_ZONE_MIN_LAST_DEATH': '60'})),
    # config/examples/death_zone.cfg, en chacun pour soi
    'zone': ('Zone de mort', 'classique', {
        'TEAM_MAX_PLAYERS': '1', 'WIN_ZONE_DEATHS': '1',
        'WIN_ZONE_MIN_ROUND_TIME': '45', 'WIN_ZONE_MIN_LAST_DEATH': '30'}),
    # config/examples/cvs_test/sumo_complete.cfg (sans SP_MIN_PLAYERS : les bots
    # restent regles par AMP)
    'sumo': ('Sumo', 'sumo', dict(_PHYSIQUE_FORT, **{
        'GAME_TYPE': '0', 'SP_GAME_TYPE': '0', 'TEAM_MAX_PLAYERS': '1',
        'WIN_ZONE_INITIAL_SIZE': '56.56', 'WIN_ZONE_EXPANSION': '-.5656',
        'SP_SIZE_FACTOR': '1', 'SIZE_FACTOR': '1', 'WIN_ZONE_MIN_ROUND_TIME': '40',
        'WIN_ZONE_MIN_LAST_DEATH': '20', 'WIN_ZONE_RANDOMNESS': '0',
        'FORTRESS_CONQUEST_RATE': '0', 'FORTRESS_DEFEND_RATE': '.6',
        'FORTRESS_CONQUEST_DECAY_RATE': '-.3', 'FORTRESS_CONQUEST_TIMEOUT': '5',
        'FORTRESS_CONQUERED_KILL_MIN': '1', 'FORTRESS_CONQUERED_KILL_RATIO': '1',
        'FORTRESS_CONQUERED_WIN': '0', 'FORTRESS_SURVIVE_WIN': '1',
        'FORTRESS_CONQUERED_SCORE': '60', 'SCORE_WIN': '0', 'SCORE_SUICIDE': '-30',
        'SCORE_KILL': '30', 'SCORE_DIE': '0', 'SP_SCORE_WIN': '0', 'LIMIT_SCORE': '600'})),
}
# mode utilise quand un vote de carte demande un autre type de carte
MODE_DU_TYPE = {'classique': 'classique', 'forteresse': 'forteresse', 'sumo': 'sumo'}
ROTATIONS = ('aucune', 'ordre', 'aleatoire')
VOTES = ('aucun', 'exclusion', 'modes_cartes')
CHEMIN_CARTE = re.compile(r'[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+.-]+)*\.aamap\.xml')
NOM_VOTE = re.compile(r'[a-z0-9_]{1,24}')


def nom_court(chemin):
    """Auteur/dossier/Ma_Carte-1.2.aamap.xml -> ma_carte"""
    base = chemin.rsplit('/', 1)[-1]
    base = re.sub(r'-\d.*$', '', base.replace('.aamap.xml', ''))
    return re.sub(r'[^a-z0-9]+', '_', base.lower()).strip('_')[:24] or 'carte'


def lire_cartes(texte, avertir):
    """« carre, hexatron, forteresse:Auteur/x.aamap.xml » -> liste de (nom, chemin, type, equipes, libelle)."""
    cartes, vus = [], set()
    for brut in re.split(r'[,;\s]+', texte.strip()):
        if not brut:
            continue
        entree = brut.strip()
        if entree.lower() in CARTES:
            nom = entree.lower()
            chemin, typ, equipes, libelle = CARTES[nom]
        else:
            typ, _, chemin = entree.rpartition(':')
            typ = typ.lower() or 'classique'
            if typ not in SECOURS or not CHEMIN_CARTE.fullmatch(chemin) or '..' in chemin.split('/'):
                avertir('TK_CARTES : « %s » ignore (nom inconnu, ou chemin du depot de ressources '
                        'invalide : Auteur/dossier/carte-1.0.aamap.xml).' % entree)
                continue
            equipes = {'classique': 0, 'forteresse': 2, 'sumo': 16}[typ]
            nom = nom_court(chemin)
            while nom in vus or nom in CARTES or nom in MODES:
                nom += '_'
            libelle = chemin.rsplit('/', 1)[-1].replace('.aamap.xml', '')
        if nom in vus:
            continue
        vus.add(nom)
        cartes.append((nom, chemin, typ, equipes, libelle))
    return cartes


class Rotation:
    """Etat des cartes et du mode, et commandes a envoyer entre deux manches."""

    def __init__(self, mode, cartes, rotation, manches, valeurs_amp, perso, hasard=None, bots=()):
        import random
        self.hasard = hasard or random.Random()
        self.mode = mode
        self.cartes = cartes
        self.rotation = rotation
        self.manches = manches
        self.amp = valeurs_amp            # '@equipe' et '@taille'
        self.perso = perso                # perso.cfg gagne toujours sur les modes
        # reglages des bots d'AMP, renvoyes aussi : des cartes mettent NUM_AIS 0, SP_MIN_PLAYERS 0
        self.bots = [tuple(l.split(' ', 1)) for l in bots]
        self.ratees = set()
        self.compte = 0
        self.vote_mode = None
        self.vote_carte = None
        self.carte = None
        self.precedente = None
        pool = self.pool(mode)
        if rotation == 'aleatoire':
            self.carte = self.hasard.choice(pool)
        else:
            self.carte = pool[0]

    def connue(self, nom):
        return next((c for c in self.cartes if c[0] == nom), None)

    def pool(self, mode):
        typ = MODES[mode][1]
        pool = [c for c in self.cartes if c[2] == typ and c[1] not in self.ratees]
        if not pool:
            nom = SECOURS[typ]
            pool = [(nom,) + CARTES[nom]]
        return pool

    def valeurs(self, mode=None, carte=None):
        """[(cle, valeur)] du mode, pour la carte : toutes les cles de BASE, dans l'ordre."""
        mode = mode or self.mode
        carte = carte or self.carte
        regles = MODES[mode][2]
        sortie = []
        for cle, defaut in BASE.items():
            v = self.perso.get(cle, regles.get(cle, defaut))
            if v == '@equipe':
                v = self.amp['TEAM_MAX_PLAYERS']
            elif v == '@taille':
                v = self.amp['SIZE_FACTOR']
            elif v == '@carte':
                v = str(carte[3] or 16)
            sortie.append((cle, v))
        for cle, v in self.bots:
            sortie.append((cle, self.perso.get(cle, v)))
        return sortie

    def lignes_initiales(self):
        return ['%s %s' % kv for kv in self.valeurs()] + ['MAP_FILE ' + self.carte[1]]

    def annonce(self):
        return 'CONSOLE_MESSAGE 0xffff7fCarte : %s  -  mode : %s' % (self.carte[4], MODES[self.mode][0])

    def fin_de_manche(self):
        """Appele sur l'evenement WAIT_FOR_EXTERNAL_SCRIPT : commandes a envoyer."""
        self.compte += 1
        mode, carte = self.mode, self.carte
        if self.vote_carte:
            carte = self.vote_carte
            if MODES[mode][1] != carte[2]:
                mode = MODE_DU_TYPE[carte[2]]
        elif self.vote_mode:
            mode = self.vote_mode
            if MODES[mode][1] != carte[2]:
                pool = self.pool(mode)
                carte = self.hasard.choice(pool) if self.rotation == 'aleatoire' else pool[0]
        elif self.rotation != 'aucune' and self.compte >= self.manches:
            pool = self.pool(mode)
            if self.rotation == 'ordre':
                i = next((k for k, c in enumerate(pool) if c[0] == carte[0]), -1)
                carte = pool[(i + 1) % len(pool)]
            else:
                autres = [c for c in pool if c[0] != carte[0]] or pool
                carte = self.hasard.choice(autres)
        if self.vote_carte or self.vote_mode or carte != self.carte:
            self.compte = 0
        self.vote_carte = self.vote_mode = None
        commandes = []
        if mode != self.mode or carte != self.carte:
            commandes += ['%s %s' % kv for kv in self.valeurs(mode, carte)]
            commandes.append('MAP_FILE ' + carte[1])
            self.precedente = (self.mode, self.carte)
            self.mode, self.carte = mode, carte
            commandes.append(self.annonce())
        commandes.append('WAIT_FOR_EXTERNAL_SCRIPT 0')
        return commandes

    def vote(self, nom):
        """Vote d'inclusion accepte (vote/<nom>) : applique a la fin de la manche."""
        if nom in MODES:
            self.vote_mode, self.vote_carte = nom, None
            return 'TeamKit : vote accepte, mode %s a la prochaine manche.' % MODES[nom][0]
        carte = self.connue(nom)
        if carte:
            self.vote_carte, self.vote_mode = carte, None
            return 'TeamKit : vote accepte, carte %s a la prochaine manche.' % carte[4]
        return None

    def carte_ratee(self):
        """Le serveur n'a pas pu lire la carte : il revient a la precedente."""
        if not self.precedente:
            return None
        rate = self.carte
        self.ratees.add(rate[1])
        self.mode, self.carte = self.precedente
        self.precedente = None
        return ('TeamKit : carte %s illisible (voir les lignes au-dessus), retiree de la '
                'rotation jusqu\'au prochain redemarrage.' % rate[1])

    def cles(self):
        return set(BASE) | {c for c, _ in self.bots} | {'MAP_FILE', 'WAIT_FOR_EXTERNAL_SCRIPT'}


def lire_perso(texte):
    """Valeurs de perso.cfg pour les reglages des modes et des bots : elles gagnent toujours."""
    perso = {}
    for ligne in texte.splitlines():
        mots = ligne.split('#')[0].split()
        if len(mots) >= 2 and (mots[0].upper() in BASE or mots[0].upper() in CLES_BOTS):
            perso[mots[0].upper()] = mots[1]
    return perso


def interpreter(vus, avertir):
    """Controle les nouveaux reglages ; renvoie un dict pret a l'emploi."""
    r = {}
    r['mode'] = vus['TK_MODE'].strip()
    if r['mode'] not in MODES:
        raise Refus('TK_MODE : mode inconnu "%s" (%s).' % (r['mode'], ', '.join(MODES)))
    r['cartes'] = lire_cartes(vus['TK_CARTES'], avertir)
    r['rotation'] = vus['TK_ROTATION'].strip()
    if r['rotation'] not in ROTATIONS:
        raise Refus('TK_ROTATION : "%s" (aucune, ordre ou aleatoire).' % r['rotation'])
    r['manches'] = int(entier('TK_ROTATION_MANCHES', vus['TK_ROTATION_MANCHES'].strip(), 1, 100))
    for cle in ('TK_BOTS', 'TK_BOTS_ADAPTATIFS'):
        if vus[cle].strip() not in ('0', '1'):
            raise Refus('%s : 0 ou 1, pas "%s".' % (cle, vus[cle].strip()))
    r['bots'] = vus['TK_BOTS'].strip() == '1'
    r['bots_adaptatifs'] = vus['TK_BOTS_ADAPTATIFS'].strip() == '1'
    r['bots_permanents'] = entier('TK_BOTS_PERMANENTS', vus['TK_BOTS_PERMANENTS'].strip(), 0, 16)
    r['bots_niveau'] = entier('TK_BOTS_NIVEAU', vus['TK_BOTS_NIVEAU'].strip(), 0, 100)
    r['votes'] = vus['TK_VOTES'].strip()
    if r['votes'] not in VOTES:
        raise Refus('TK_VOTES : "%s" (aucun, exclusion ou modes_cartes).' % r['votes'])
    r['votes_joueurs'] = int(entier('TK_VOTES_JOUEURS', vus['TK_VOTES_JOUEURS'].strip(), 1, 32))
    r['votes_anciennete'] = entier('TK_VOTES_ANCIENNETE', vus['TK_VOTES_ANCIENNETE'].strip(), 0, 3600)
    modes = []
    for m in re.split(r'[,;\s]+', vus['TK_VOTES_MODES'].strip().lower()):
        if not m:
            continue
        if m in MODES:
            if m not in modes:
                modes.append(m)
        elif m != 'aucun':
            avertir('TK_VOTES_MODES : mode inconnu « %s » ignore (%s).' % (m, ', '.join(MODES)))
    r['votes_modes'] = modes
    return r


CLES_BOTS = ('MIN_PLAYERS', 'SP_MIN_PLAYERS', 'NUM_AIS', 'SP_NUM_AIS', 'AI_IQ', 'SP_AI_IQ',
             'AUTO_AIS', 'SP_AUTO_AIS', 'AUTO_IQ', 'SP_AUTO_IQ', 'TEAM_BALANCE_WITH_AIS',
             'SP_TEAM_BALANCE_WITH_AIS')


def bloc_bots(r, min_players):
    if not r['bots']:
        # SP_MIN_PLAYERS 1 : un joueur seul attend du monde, sans adversaire
        return ['MIN_PLAYERS 0', 'SP_MIN_PLAYERS 1', 'NUM_AIS 0', 'SP_NUM_AIS 0',
                'AUTO_AIS 0', 'SP_AUTO_AIS 0', 'AUTO_IQ 0', 'SP_AUTO_IQ 0',
                'TEAM_BALANCE_WITH_AIS 0', 'SP_TEAM_BALANCE_WITH_AIS 0']
    a = '1' if r['bots_adaptatifs'] else '0'
    return ['MIN_PLAYERS ' + min_players, 'SP_MIN_PLAYERS %d' % max(4, int(min_players)),
            'NUM_AIS ' + r['bots_permanents'], 'SP_NUM_AIS ' + r['bots_permanents'],
            'AI_IQ ' + r['bots_niveau'], 'SP_AI_IQ ' + r['bots_niveau'],
            'AUTO_AIS ' + a, 'SP_AUTO_AIS ' + a, 'AUTO_IQ ' + a, 'SP_AUTO_IQ ' + a,
            'TEAM_BALANCE_WITH_AIS 1', 'SP_TEAM_BALANCE_WITH_AIS 1']


def noms_de_vote(r):
    """Noms que les joueurs peuvent voter : modes choisis + cartes de la liste."""
    if r['votes'] != 'modes_cartes':
        return [], []
    return list(r['votes_modes']), [c[0] for c in r['cartes']]


def bloc_votes(r):
    if r['votes'] == 'aucun':
        return ['ALLOW_VOTING 0']
    lignes = ['ALLOW_VOTING 1',
              # le vote est refuse si les votants en ligne sont <= MIN_VOTERS (eVoter.cpp)
              'MIN_VOTERS %d' % (r['votes_joueurs'] - 1),
              'VOTING_MATURITY ' + r['votes_anciennete']]
    modes, cartes = noms_de_vote(r)
    if modes or cartes:
        # 20 = joueur ordinaire (tAccessLevel_Program) ; par defaut, seuls les moderateurs
        # peuvent proposer un /vote include
        lignes.append('ACCESS_LEVEL_VOTE_INCLUDE 20')
        aide = ['Dans le chat : /vote include NOM  (ex. /vote include %s)'
                % (modes[0] if modes else cartes[0]),
                'Puis chacun vote : Echap > Vote > Approuve ou Desapprouve.',
                'Le changement a lieu a la manche suivante.']
        if modes:
            aide.append('Modes : ' + ', '.join(modes))
        if cartes:
            aide.append('Cartes : ' + ', '.join(cartes))
        lignes.append('ADD_HELP_TOPIC votes "Changer de mode ou de carte par un vote" "%s"'
                      % '\\n'.join(aide))
    return lignes


def preparer(texte_amp, texte_perso, port, joueurs, avertir, hasard=None):
    """(contenu de settings_custom.cfg en str, Rotation ou None, fichiers de vote)."""
    vus = lire_cles(texte_amp, lambda m: None)
    lignes = [
        '# settings_custom.cfg - REECRIT A CHAQUE DEMARRAGE par lancer-armagetron.py.',
        '# Ne le modifie pas : change les reglages dans AMP, ou ecris dans perso.cfg.',
        '',
        '# --- reglages d\'AMP (reglages-amp.cfg) ---',
    ]
    lignes += lire_reglages_amp(texte_amp, avertir)
    r = interpreter(vus, avertir)
    amp = {'TEAM_MAX_PLAYERS': vus['TEAM_MAX_PLAYERS'].strip(), 'SIZE_FACTOR': vus['SIZE_FACTOR'].strip()}
    perso = lire_perso(texte_perso)
    bots = bloc_bots(r, vus['MIN_PLAYERS'].strip())
    rotation = Rotation(r['mode'], r['cartes'], r['rotation'], r['manches'], amp, perso, hasard, bots)
    if not [c for c in r['cartes'] if c[2] == MODES[r['mode']][1]]:
        avertir('aucune carte de la liste ne convient au mode %s : carte %s utilisee.'
                % (MODES[r['mode']][0], rotation.carte[4]))
    lignes += ['', '# --- bots ---'] + bots
    lignes += ['', '# --- votes ---'] + bloc_votes(r)
    lignes += ['', '# --- mode %s, carte %s ---' % (r['mode'], rotation.carte[0])]
    lignes += rotation.lignes_initiales()
    lignes += ['', '# --- perso.cfg ---']
    for brute in texte_perso.splitlines():
        ligne, retires = vers_latin1(brute.rstrip('\r'))
        if retires and not ligne.lstrip().startswith('#'):
            avertir('perso.cfg : caracteres retires : %s' % ' '.join(retires))
        lignes.append(ligne)
    actif = r['rotation'] != 'aucune' or r['votes'] == 'modes_cartes'
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
        '# pause entre deux manches pour la rotation et les votes (3 s au plus)',
        'WAIT_FOR_EXTERNAL_SCRIPT %d' % actif,
        'WAIT_FOR_EXTERNAL_SCRIPT_TIMEOUT 3',
        '',
    ]
    modes, cartes = noms_de_vote(r)
    fichiers = {}
    for nom in modes + cartes:
        texte = ('# Vote TeamKit « %s » : ce fichier ne contient rien a dessein.\n'
                 '# lancer-armagetron.py voit le vote accepte dans la console et applique\n'
                 '# le changement entre deux manches. Recree a chaque demarrage.\n' % nom)
        fichiers[nom] = texte
        fichiers[nom + '.cfg'] = texte
    return '\n'.join(lignes), (rotation if actif else None), fichiers


def construire(texte_amp, texte_perso, port, joueurs, avertir):
    """Contenu de settings_custom.cfg (str, a ecrire en Latin-1)."""
    return preparer(texte_amp, texte_perso, port, joueurs, avertir)[0]


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


# Vote d'inclusion accepte et execute (message vote_include_message : anglais, repris
# tel quel en francais ; traduit seulement en allemand et en polonais). Le numero
# entre crochets est celui du joueur qui a propose le vote, pas toujours 0.
VOTE_INCLUS = re.compile(r'^\[\d+\] (?:Including file|Binde|Zalaczanie pliku) vote/([A-Za-z0-9_]+?)(?:\.cfg)?[. ]')
# Carte illisible : map_file_load_failure_self puis map_file_reverting (pas traduits en francais)
CARTE_RATEE = re.compile(r'could not be loaded or parsed|Reverting to last known working map')


class Filtre:
    """Transforme chaque ligne du serveur (deja en str) en 0, 1 ou 2 lignes pour AMP."""

    def __init__(self, port, rotation=None):
        self.port = port
        self.noms = {}          # nom de journal -> nom affiche
        self.pret = False
        self.rotation = rotation
        self.a_envoyer = []     # commandes pour le serveur, envoyees par la boucle principale
        if rotation:
            cles = '|'.join(sorted(re.escape(c) for c in rotation.cles()))
            # echo des reglages changes entre deux manches : « [0] MAP_FILE a change ... »
            self.echo = re.compile(r'^\[\d+\] (?:Setting )?(?:%s) ' % cles)

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
            if self.rotation and evt == 'WAIT_FOR_EXTERNAL_SCRIPT':
                # fin de manche : le serveur attend nos reglages (3 s au plus)
                self.a_envoyer += self.rotation.fin_de_manche()
            elif self.rotation and evt == 'NEW_ROUND':
                self.a_envoyer.append('WAIT_FOR_EXTERNAL_SCRIPT 1')
            return []           # le reste du ladderlog reste dans var/ladderlog.txt
        if BRUIT.match(l):
            return []
        sortie = []
        if self.rotation:
            if self.echo.match(l):
                return []
            m = VOTE_INCLUS.match(l)
            if m:
                message = self.rotation.vote(m.group(1).lower())
                if message:
                    sortie.append(message)
            elif CARTE_RATEE.search(l):
                message = self.rotation.carte_ratee()
                if message:
                    sortie.append(message)
        if l.startswith('TeamKit'):
            l = ' ' + l          # seules nos lignes commencent par « TeamKit »
        sortie.insert(0, l)
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
    for message in controler_version(os.path.join(SERVEUR, 'usr')):
        dire('TeamKit : ATTENTION, ' + message)
    return 0


def lire_defauts(dossier_config):
    """Valeurs de settings.cfg puis settings_dedicated.cfg (la derniere gagne)."""
    vals = {}
    for nom in ('settings.cfg', 'settings_dedicated.cfg'):
        try:
            with open(os.path.join(dossier_config, nom), encoding='latin-1') as f:
                for ligne in f:
                    mots = ligne.split('#')[0].split()
                    if len(mots) >= 2:
                        vals[mots[0].upper()] = mots[1]
        except OSError:
            pass
    return vals


def controler_version(prefixe):
    """Compare BASE et les cartes incluses a la version installee (messages d'alerte)."""
    messages = []
    defauts = lire_defauts(os.path.join(prefixe, 'etc', 'games', 'armagetronad-dedicated'))
    if not defauts:
        return ['settings.cfg du serveur introuvable : valeurs par defaut des modes non verifiees.']
    for cle, v in BASE.items():
        if v.startswith('@') or cle not in defauts:
            continue
        try:
            egal = float(defauts[cle]) == float(v)
        except ValueError:
            egal = defauts[cle] == v
        if not egal:
            messages.append('defaut du jeu change pour %s : %s (le lanceur suppose %s).'
                            % (cle, defauts[cle], v))
    inclus = os.path.join(prefixe, 'share', 'games', 'armagetronad-dedicated', 'resource', 'included')
    for nom in list(CARTES)[:8]:
        if not os.path.isfile(os.path.join(inclus, CARTES[nom][0])):
            messages.append('carte %s absente des cartes fournies avec le jeu.' % CARTES[nom][0])
    return messages


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

def tourner_journal(nom, limite=20 * 1024 * 1024):
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
        contenu, rotation, fichiers = preparer(texte_amp, texte_perso, port, joueurs,
                                               lambda m: dire('TeamKit : ' + m))
    except Refus as e:
        dire('ERREUR : ' + str(e))
        dire('Corrige ce reglage dans l\'onglet Configuration d\'AMP, puis relance.')
        return 1
    with open(SORTIE, 'w', encoding='latin-1', newline='\n') as f:
        f.write(contenu)
    # fichiers de vote : /vote include <nom> lit config/vote/<nom> (eVoter.cpp). Le dossier
    # appartient au lanceur ; des votes faits main vont dans var/vote/<nom>.cfg.
    dossier_vote = os.path.join(CONFIG, 'vote')
    shutil.rmtree(dossier_vote, ignore_errors=True)
    if fichiers:
        os.makedirs(dossier_vote)
        for nom, texte in fichiers.items():
            with open(os.path.join(dossier_vote, nom), 'w', encoding='latin-1', newline='\n') as f:
                f.write(vers_latin1(texte)[0])
    if rotation:
        dire('TeamKit : mode %s, carte %s, rotation %s%s, votes %s.' % (
            MODES[rotation.mode][0], rotation.carte[4], rotation.rotation,
            ' toutes les %d manches' % rotation.manches
            if rotation.rotation != 'aucune' and rotation.manches > 1 else '',
            'des modes et des cartes (/help votes)' if fichiers else 'sans mode ni carte'))
    tourner_journal('ladderlog.txt')
    tourner_journal('scorelog.txt')

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
                proc.stdin.write(vers_latin1(commande)[0].encode('latin-1') + b'\n')
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

    filtre = Filtre(port, rotation)

    def surveiller_pret():
        time.sleep(30)
        if not filtre.pret and proc.poll() is None:
            dire('TeamKit : ATTENTION, le port %d n\'est toujours pas ouvert apres 30 secondes.' % port)
    threading.Thread(target=surveiller_pret, daemon=True).start()

    for brute in proc.stdout:
        l = brute.decode('latin-1').rstrip('\r\n')
        for s in filtre.ligne(l):
            dire(s)
        while filtre.a_envoyer:
            envoyer(filtre.a_envoyer.pop(0))
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
