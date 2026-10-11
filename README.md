# AMPTemplates-Armagetron — Armagetron Advanced dedicated server for AMP

**AMP Generic Module** template for the official dedicated server of **Armagetron Advanced**
(<https://www.armagetronad.org/>, source <https://gitlab.com/armagetronad/armagetronad>), the free
and open source 3D light cycle game, also on Steam as **Retrocycles** (app 1306180, free).
Written for TeamKit, a free French game host, on 10 Oct 2026. CubeCoders ships no Armagetron
template (checked in `CubeCoders/AMPTemplates`, branch `main`, 10 Oct 2026).

> Résumé en français à la fin du fichier.

## Which version, and why not the Debian package

| Source | Version | Verdict |
|---|---|---|
| Latest stable release (8 Oct 2026, download.armagetronad.org) | **0.2.9.3.1** | **used** |
| Steam (Retrocycles, last announcement 18 Apr 2026) | 0.2.9.3.0 | what most players run |
| Debian 13 `armagetronad-dedicated` (in `cubecoders/ampbase:debian`) | 0.2.9.1.1 | **not used**: lacks a server-side security fix |

0.2.9.3.1 "has a security fix, users were able to delete objects owned by other clients" (release
notes). The fix (commit `444c418b`, *Check object owner when destroying netobject*) is in
`net_destroy_handler` (`src/network/nNetObject.cpp`): the **server** now refuses a destroy message
from a client that does not own the object. A server built before it is exposed, whatever the
clients run. Debian 13 ships 0.2.9.1.1 (2023), so the template does not use it.

No compiling is needed: the project publishes the **official dedicated server as an AppImage**, and
its stable URL always serves the latest stable release (it is the URL AppImageUpdate uses, written
in the AppImage itself):

    https://download.armagetronad.org/appimage/ArmagetronAdvancedDedicated.AppImage

On 10 Oct 2026 this file was byte-identical to Launchpad's `0.2.9.3.1/ArmagetronAdvancedDedicated.AppImage`
(SHA-256 `3d713db02966c0d91fba8a21ee6902281d6a3ff70b7e12e6164bb2df361cd94b`).

**Client compatibility.** Every 0.2.9 release speaks network protocol 17 (`0.2.9_alpha` in the
version table of `src/network/nConfig.cpp`), and the server accepts older protocols by default
(`BACKWARD_COMPATIBILITY 1000`). The real 0.2.9.3.1 client showed up as `0.2.9_alpha (ID: 17)` in
`PLAYERS`. So Steam's 0.2.9.3.0 and the website's 0.2.9.3.1 play on this server.

## Files

| File | Role |
|---|---|
| `armagetron.kvp`, `armagetron*.json`, `manifest.json` | the AMP template |
| `scripts/AMP_reglages.cfg` | settings model; AMP renders it to `reglages-amp.cfg` (`ConfigType: template`) |
| `scripts/lancer-armagetron.py` | install and start script (Python 3, see below) |
| `verifier.py` | pre-push checks, must print `Tout est bon.` |

Both `scripts/` files are fetched from this repository (raw.githubusercontent.com, branch `main`)
at each Update, so **the repository must be public**.

Instance layout (`armagetron/`): `serveur/` = extracted AppImage (replaced at each Update),
`config/settings_custom.cfg` (rewritten at each start), `var/` (ladderlog, bans, scores),
`donnees/` (downloaded map resources), `perso.cfg` (yours, never overwritten).

## Update stages

1. **FetchURL** the official AppImage (stable URL above);
2. **FetchURL** `lancer-armagetron.py` and 3. `AMP_reglages.cfg` from this repository;
4. `python3 lancer-armagetron.py installer`: checks the download is an ELF, runs
   `--appimage-extract` (**no FUSE needed**, AMP containers have none) into a temporary folder,
   swaps it into `serveur/`, creates `perso.cfg` once, prints
   `This is armagetronad-dedicated version 0.2.9.3.1.` — or the missing libraries if it cannot run.

Container `cubecoders/ampbase:debian` (Debian 13), **required**. The extracted server only needs
libraries already in the image (it bundles libxml2, libcurl and ZThread); `python3` is added by
`ExtraContainerPackages` for the launcher (already in the image on 10 Oct 2026, listed to be safe).
The launcher runs the binary directly with `LD_LIBRARY_PATH=serveur/usr/lib`, i.e. with the
bundled libraries first, unlike the AppImage's `AppRun`, which puts system libraries first.

## How the server is started

AMP runs `python3 -u lancer-armagetron.py lancer <port> <max players>`, which:

1. reads `reglages-amp.cfg` (written by AMP, UTF-8), checks every value, appends `perso.cfg`, then
   the lines the template needs (`SERVER_PORT`, `MAX_CLIENTS`, `CONSOLE_LADDER_LOG 1`,
   `LADDERLOG_WRITE_PLAYER_ENTERED/LEFT/RENAMED 1`), and writes **`config/settings_custom.cfg` in
   Latin-1** (see *Text values*). `settings_dedicated.cfg` includes `settings_custom.cfg` last, after
   its own game settings, so these win;
2. starts `armagetronad-dedicated --userconfigdir config --vardir var --userdatadir donnees`
   (with `PR_SET_PDEATHSIG`: if the launcher is SIGKILLed, the server dies too and frees the port — tested);
3. relays the AMP console to the server's **stdin**, converted to Latin-1. The dedicated server
   reads console commands there at owner level: `SAY`, `KICK`, `BAN`, `BAN_IP`, `UNBAN_IP`,
   `BAN_LIST`, `PLAYERS`, `RENAME`, any setting (`SAY`, `PLAYERS`, `BAN`, `BAN_IP`, `UNBAN_IP`,
   `BAN_LIST`, `RENAME` tested);
4. filters the server output: Latin-1 → UTF-8; drops lines repeated in a loop (`Answering ping poll`
   for every player looking at the server list, `Waiting for real players` in a loop while nobody plays, an unknown
   `HUD_CACHE_THRESHOLD` in the official `settings.cfg`); turns ladderlog events into player lines:

   ```
   [L] PLAYER_ENTERED essai 172.17.0.30 essai                -> TeamKit : arrivee de essai
   [L] PLAYER_RENAMED essai kevin_te 172.17.0.30 Kévin Té   -> TeamKit : depart de essai
                                                             -> TeamKit : arrivee de Kévin Té
   [L] PLAYER_LEFT kevin_te 172.17.0.30                      -> TeamKit : depart de Kévin Té
   ```

   The leave event only carries the log name (`kevin_te`), so the launcher remembers which screen
   name goes with it; colour codes are stripped. Other ladderlog events stay in `var/ladderlog.txt`
   (renamed `.1` beyond 20 MB, like `scorelog.txt`);
5. prints `TeamKit : Armagetron Advanced pret sur le port 4534 (UDP).` when the server logs
   `Bound socket to *.*.*.*:4534.` (`Console.AppReadyRegex`); a warning after 30 s otherwise;
6. on SIGTERM (AMP stop) sends `QUIT`: clean exit, code 0, in under a second (tested). Hard
   kill after 10 s.

## Settings exposed in AMP (French UI)

| AMP setting | Game setting | Default |
|---|---|---|
| Port du jeu (Network tab) | `SERVER_PORT` | 4534/UDP (the game's default) |
| Joueurs maximum | `MAX_CLIENTS` (`$MaxUsers`) | 16, at most **32** (hard limit of the dedicated build) |
| Nom du serveur | `SERVER_NAME` | `0x3d7dff[0xffffffFR0xff4646]0xffffff TeamKit · Serveur francophone` |
| Afficher dans la liste officielle | `TALK_TO_MASTER` | **on** (the game's dedicated default is off) |
| Description dans la liste | `SERVER_OPTIONS` (240 chars) | French TeamKit text + Discord |
| Site web du serveur | `URL` (75 chars) | `https://teamkit.fr` |
| Langue du serveur | `LANGUAGE_FIRST` | `Francais` |
| Titre / Message d'accueil | `TITLE_OF_DAY` / `MESSAGE_OF_DAY` | TeamKit welcome, `\n` = new line |
| Manches par match | `LIMIT_ROUNDS` | 10 |
| Joueurs par équipe | `TEAM_MAX_PLAYERS` | 5 |
| Bots : compléter jusqu'à | `MIN_PLAYERS` | 0 |
| Vitesse des motos / Taille de l'arène | `SPEED_FACTOR` / `SIZE_FACTOR` | 0 / 0 |

Plus the game modes, map rotation, bots and votes settings described in the next section.

Invalid values (not a number, out of range, unknown language, URL starting with a quote) stop the
start with a French message naming the setting. Anything else goes in **`perso.cfg`**, read after
the AMP settings (so it can override them) and before the template's fixed lines. A value set in
`perso.cfg` also wins over the game modes (the launcher re-sends it at each mode change).

**The server language matters for players**: the server translates its messages itself
(`sn_ConsoleOut` turns the `tOutput` into a string before sending), so every player gets
"X est entré(e) dans le jeu", "C'est parti (round 1 sur 10)!" in French whatever their own language.

### Server name: no emoji, but colours

- The game's internal encoding is **Latin-1** (`st_internalEncoding("latin1")`, `src/tools/tLocale.cpp`)
  and its font is two 16×16 bitmap grids (`textures/font.png`, `font_extra.png`) covering exactly
  ASCII and Latin-1 160–255. **Emoji cannot be displayed** (🇫🇷 would come out as mojibake); the
  launcher removes them and says so in the console. Accents and `·` display fine (seen in the client).
- **Colour codes** `0xRRGGBB` are shown in the server browser: the client's `settings.cfg` sets
  `FILTER_COLOR_SERVER_NAMES 0`; only dark colours are filtered (`FILTER_DARK_COLOR_SERVER_NAMES`,
  `tColor::IsDark`). Many listed servers use them. The default name shows `[FR]` with a blue `[`,
  white `FR`, red `]`, then `TeamKit · Serveur francophone` in white — checked in the real client's
  server browser.
- Consequence: any `0x` in a text starts a colour code and eats 8 characters.

### Text values

AMP writes values verbatim. The game reads a text setting as the **whole rest of the line**
(`tConfItemLine::ReadVal`), so `#` is **not** a comment there, and it interprets `\n` (new line),
`\\` and `\"`. A line ending with `\` is glued to the next one (`tConfItemBase::LoadAll`). So the
launcher:

- converts to Latin-1: `—`/`–` → `-`, curly quotes → straight, `œ` → `oe`, `€` → `EUR`, other
  accented letters → base letter, emoji and the like removed (console notice);
- in the name, description and title, doubles every `\` (no line break there);
- in the welcome message, keeps `\n` as a line break and closes a trailing odd `\`;
- removes spaces from the URL.

`verifier.py` replays this on the real launcher code and re-reads the result with a Python copy of
the game's parser. Tested in the client: the welcome window showed two lines with accents, `#`,
`{}`, `"` and `C:\temp\` intact.

## Game modes, map rotation, bots and player votes (added 11 Oct 2026)

### Map rotation: done by the launcher

0.2.9.3.1 has **no map rotation** (no `MAP_ROTATION` or similar anywhere in the source; it exists in
forks and in the 0.4 branch only). The launcher does it with the hook the game provides for scripts:
with `WAIT_FOR_EXTERNAL_SCRIPT 1`, at the end of each round (`GS_PLAY` in `gGame.cpp`) the server
writes the ladderlog event `WAIT_FOR_EXTERNAL_SCRIPT`, then waits (`WAIT_FOR_EXTERNAL_SCRIPT_TIMEOUT 3`
seconds at most) while still reading stdin. The launcher answers with the next `MAP_FILE` and the
mode settings, then `WAIT_FOR_EXTERNAL_SCRIPT 0`; on `NEW_ROUND` it sets it back to 1.

**When a new `MAP_FILE` is used**: at the next grid creation. Between rounds the server compares the
map with the last one (`GS_TRANSFER_SETTINGS`), sends the settings to the clients, then parses the
map (`GS_CREATE_GRID`). If the map cannot be loaded, the server prints `The map … could not be loaded
or parsed` and `Reverting to last known working map …`; the launcher then drops that map from its
rotation until the next start (tested with a non-existent path).

**Downloads**: maps are resources. The server and every client look in their local cache, then
download from `RESOURCE_REPOSITORY_SERVER` (sent by the server; default
`http://resource.armagetronad.net/resource/`) — `tResourceManager::locateResource`. Tested: the server
saved them in `donnees/resource/automatic/…`, the real client in `~/.armagetronad/resource/automatic/…`,
with no action from the player. Maps of the `resource/included` folder ship with the game and are
never downloaded.

**Maps change settings too.** A map file can contain `<Setting>` tags, and they stay after the map:
`fort2` sets `SP_MIN_PLAYERS 0`, `SP_TEAMS_MAX 2`, `NUM_AIS 0`…, others `FORTRESS_MAX_PER_TEAM`,
`CYCLE_ACCEL_RIM`, `SPAWN_POINT_GROUP_SIZE`. At every map or mode change the launcher therefore
re-sends all the mode keys, these keys and the bot settings, before the map applies its own.

Settings: *Cartes en rotation* (list), *Rotation des cartes* (`aleatoire` random — never the same map
twice in a row —, `ordre`, `aucune`), *Changer de carte toutes les N manches*. Each mode only takes
maps of its type; with none in the list, a built-in map of that type is used.

### Maps (all loaded on the server and in the real client on 11 Oct 2026)

| Name (votes, list) | Map | Type | Source |
|---|---|---|---|
| `carre` | Anonymous/polygon/regular/square-1.0.1 | no zone (default map of the game) | shipped |
| `diamant` | Anonymous/polygon/regular/diamond-1.0.2 | no zone | shipped |
| `polygone` | Anonymous/polygon/regular/40-gon-0.2 | no zone | shipped |
| `inaktek` | Your_mom/clever/inaktek-0.7.2 | no zone | shipped |
| `repeat` | Your_mom/clever/repeat-0.3.2 | no zone | shipped |
| `hexatron` | Luke-Jr/Classic/HexaTRON-0.4.3 | no zone | repository |
| `croix` | Your_mom/clever/ironcross-0.8.3 | no zone | repository |
| `tripath` | Your_mom/clever/tripath-0.3.6 | no zone | repository |
| `dents` | Your_mom/clever/twoxdentedsquare-0.0.2 | no zone | repository |
| `fort2` | Z-Man/fortress/for_old_clients-0.1.0 | fortress, 2 teams | shipped |
| `fort4` | Z-Man/fortress/fourfold_for_old_clients-0.1.0 | fortress, 4 teams | shipped |
| `fortcarre` | Luke-Jr/SoloFortress/Square-0.2.1 | fortress, 4 teams | repository |
| `egalite` | Luke-Jr/WildFortress/equal-0.3.1 | fortress, 2 teams (2 zones each) | repository |
| `sumo4` | Z-Man/fortress/sumo_4x4-0.1.1 | sumo, 16 zones | shipped |
| `fosse` | Z-Man/fortress/pit_4x4-0.1.1 | sumo, 16 zones | repository |

All use the map DTDs shipped with 0.2.9 (`AATeam/map-0.2.8.0*.dtd`). Rejected while choosing:
`spinning_square` (0.4 DTD `map-0.3.1-a`), `ctfsty` (fork DTD `_pig2`), `Weird` (one spawn point),
`hype` (a fortress zone in a 2-player map). Another repository map can be added by its path
(`Auteur/dossier/carte-1.0.aamap.xml`, prefixed `forteresse:` or `sumo:` if it has zones, counted
as 2 teams); its vote name is derived from the file name.

### Game modes

| Mode (`TK_MODE`, vote name) | Rules | Maps |
|---|---|---|
| `classique` | free for all (`TEAM_MAX_PLAYERS 1`), last one alive wins | no zone |
| `equipes` (**default**) | the game's own rules, untouched: teams of *Joueurs par équipe*, formed automatically | no zone |
| `forteresse` | `examples/fortress_soccer.cfg` + `cvs_test/fortress_physics.cfg` + `fortress_scoring.cfg` + the three `WIN_ZONE` lines of `fortress_complete.cfg`; `TEAMS_MIN 2`, `TEAMS_MAX` = teams of the map | fortress |
| `zone` (zone de mort) | `examples/death_zone.cfg` (`WIN_ZONE_DEATHS 1`, zone after 45 s / 30 s without a death), free for all | no zone |
| `sumo` | `examples/cvs_test/sumo_complete.cfg` (without its `SP_MIN_PLAYERS 0`: bots stay under AMP's control) | sumo |

Every mode writes the same full set of keys (`BASE` in the launcher, the game defaults from
`settings.cfg` + `settings_dedicated.cfg` of 0.2.9.3.1), so switching back from fortress or sumo
really resets everything. The Update stage compares `BASE` with the installed version's files and
warns if a default changed. In the test container, `classique`, `forteresse`, `zone` and `sumo` were
switched to (start setting and votes) and played on each of their maps (sumo: "awarded 30 points for
conquering…", "eradicated by its collapsing zone"); `equipes` is the game's default, played since day
one. Not observed: the death zone itself (the idle test player always died before 45 s).

### Bots

| AMP setting | Game settings |
|---|---|
| Bots activés | off: `MIN_PLAYERS 0`, `SP_MIN_PLAYERS 1`, `NUM_AIS 0`, `TEAM_BALANCE_WITH_AIS 0`… — a lone player rides alone (tested); on: a lone player faces at least 3 bots (`SP_MIN_PLAYERS 4`, game default) |
| Bots : compléter les parties jusqu'à | `MIN_PLAYERS` (2+ players connected) |
| Bots toujours présents | `NUM_AIS` and `SP_NUM_AIS` |
| Niveau des bots | `AI_IQ` and `SP_AI_IQ` (20 / 50 / 75 / 100) |
| Bots qui s'adaptent aux joueurs | `AUTO_AIS`, `AUTO_IQ` and their `SP_` versions |

Bots never reach AMP's player list: the server writes `PLAYER_ENTERED` only for humans
(`player_.IsHuman()` in `ePlayer.cpp`), and the list is built from that event — checked in every test
(3 bots in game, one player in the list). Some maps disable bots themselves (`fort2`: `NUM_AIS 0`,
`SP_MIN_PLAYERS 0`) for the rounds they are played.

### Player votes

The vote is the game's own **include vote** (`eVoteItemInclude`, `eVoter.cpp`, compiled in official
builds): `/vote include NAME` loads the file `vote/NAME` from the config folders. The launcher writes
one empty file per mode and per map of the list in `config/vote/` (`NAME` and `NAME.cfg`), recreated at
each start; it sees the accepted vote in the console (`Including file vote/NAME.`) and applies the
change **at the end of the round**, like the rotation. Custom vote files go in `var/vote/NAME.cfg`.

**How a player votes:**

1. In the chat (Enter): `/vote include forteresse` (or a map: `/vote include hexatron`), lowercase.
   `/help votes` lists the names, in French.
2. The others: **Escape → Vote** (first menu line while a poll is open) → the poll, then **right
   arrow** to *Approuve* (or *Désapprouve*), then Escape to close the menu: the vote is sent when the
   menu closes.
3. The poll passes when more than half the voters approve (the proposer counts as yes); after 1 minute
   non-voters start being ignored, one per minute; it expires after 60 s + 15 s per voter.

Guards, from the code: `MIN_VOTERS` (a poll is refused while voters ≤ this; AMP asks for *players online*,
default 2 → `MIN_VOTERS 1`; tested: alone → "Sondage refusé, trop peu d'utilisateurs en ligne"),
`VOTING_MATURITY` (seconds online under the same name before proposing, default 60), the vote spam
protection of the game, and the path check (`/vote include ../perso.cfg` → "User given path … is a
relative path", tested). `ACCESS_LEVEL_VOTE_INCLUDE` is set to 20 (ordinary player); by default only
moderators may propose include votes. **Voters are counted per IP address**: two players behind the
same box count as one (in the test, two clients from the same address: the second one's approval
did not count and the poll expired).

Tested with two real clients from two addresses: proposal by one, approval through the menu by the
other → accepted, mode switched at the next round.

### Existing instances (Fetch Latest does not update the form)

An instance keeps the settings form it was created with. After Update (new launcher and model), AMP
renders the new model with the old form: the `TK_` lines stay as `{{TK_…}}` or come out empty. The
launcher then uses `NOUVELLES` defaults, which reproduce the **previous behaviour exactly**
(mode = the game's rules, map `carre`, no rotation, the game's original votes, same bots), prints one
console line about it, and `verifier.py` checks that every game value is unchanged. To get the new
form: stop the instance, copy the template's manifests into it (TeamKit's
`dedie/reporter-console-template.py`, which also copies `configmanifest.json` / `metaconfig.json`),
start it; or create a new instance.

## Server list (master servers)

With *Afficher dans la liste officielle* on, the server registers with the four master servers of
`master.srv` (master1/2.armagetronad.org, master3/4.armagetronad.net). Tested from a bridged
container like AMP's: all four answered (`Connexion reussie`), and the master reported the host's
public address `51.254.47.151:4534`. **Not verified**: that the server then shows in the Internet
list — it needs the UDP port to be reachable from outside, which the test container did not have
(AMP opens it for a real instance).

Players: *Jeu en réseau → Jeu en réseau via Internet* (English: *Play Game → Multiplayer → Online
Multiplayer*), or *Jeu en réseau → connection perso.* (*Custom Connect*): address in the first
field, port in the second (4534 is pre-filled).

## Admin rights in game

`ADMIN_PASS` **does not exist** in official builds: they are compiled with the authentication
system (`--enable-armathentication` defaults to yes → `KRAWALL_SERVER`), and the server answers
`Command ADMIN_PASS unknown.` (tested). In-game moderators would need local accounts
(`LOCAL_USER`, documented in the shipped `settings_authentication.cfg`) or global IDs; not set up
nor tested here. The AMP console is owner-level anyway.

## Console and player list

Real lines (0.2.9.3.1, French):

```
TeamKit : Armagetron Advanced pret sur le port 4534 (UDP).   <- AppReadyRegex
TeamKit : arrivee de essai                                    <- UserJoinRegex
TeamKit : depart de Kévin Té                                  <- UserLeaveRegex
[1] essai est entre(e) dans le jeu.
[1] essai: salut                                              (chat, not parsed: ambiguous)
[0] Admin: Bonjour à tous - message de la console d'AMP é     (SAY from AMP)
[0] Players from IP 172.17.0.30 are banned for 5 minutes. Reason: essai de bannissement TeamKit
```

Normal noise: on start and on each master registration, a few `Connexion au serveur maitre…`
lines; when the server empties it closes and reopens its socket (`Closing socket` / `Bound socket`).
A second UDP socket on a random port is for outgoing master/ping traffic; nothing to open.
Bans are kept in `var/bans.txt` across restarts (tested with `BAN_IP` + restart + `BAN_LIST`).

## Resources (measured)

| | |
|---|---|
| RAM | server 8.3 MB RSS (idle, and with 1 player + 3 bots playing), 9.4 MB with the map rotation running; launcher 14–16 MB |
| Disk | 2.4 MB AppImage + 6 MB extracted, plus `var/` logs |
| CPU | low; `DEDICATED_FPS 40` simulation steps per second |
| Start | ready line within the first 4 s of every test start |

## Before pushing

```
python verifier.py
```

Must print `Tout est bon.`: JSON, includes, port refs, complete `Console.*`/`Limits.*` block,
settings ↔ model ↔ launcher keys, defaults, a round trip through the real launcher and a copy of the
game's parser (empty, spaces, accents, `#`, `{`, `"`, backslashes, emoji, em dash, colour codes,
`\n`), refused values, the output filter and console regexes on real lines, download URLs, LF endings.

## Install in AMP

ADS → Configuration → Instance Deployment → **Configuration Repositories**: add
`hydrocut/AMPTemplates-Armagetron:main`, save, **Fetch latest**. Create Instance → **Armagetron
Advanced (TeamKit)** → **Update** (must print `This is armagetronad-dedicated version 0.2.9.3.1.`)
→ **Start**.

## Credits

Armagetron Advanced is free software (GPL-2.0+) by the Armagetron Advanced team. This repository
only contains the template; the server is the project's official AppImage, downloaded at Update.

---

## Résumé en français

Template AMP pour le **serveur dédié officiel d'Armagetron Advanced** (motos lumineuses façon Tron,
gratuit et libre ; sur Steam il s'appelle **Retrocycles**). Le serveur est l'**AppImage officielle**,
téléchargée à chaque Update depuis l'adresse stable du projet (toujours la dernière version stable,
**0.2.9.3.1** le 10 oct. 2026), puis extraite sans FUSE : rien à compiler. Le paquet Debian
(0.2.9.1.1) n'est **pas** utilisé : il lui manque un correctif de sécurité côté serveur sorti le
8 oct. 2026. Tous les clients 0.2.9 (Steam, site officiel) parlent le même protocole. Conteneur
obligatoire. Un seul port, **4534 en UDP**.

- **Liste des serveurs** : annonce aux 4 serveurs maîtres officiels activée par défaut (réglable).
  Nom par défaut : `[FR] TeamKit · Serveur francophone`, avec `[FR]` en bleu-blanc-rouge. **Le jeu
  n'affiche pas les émojis** (il ne connaît que le Latin-1) : le lanceur les retire et le dit ; les
  couleurs `0xRRGGBB`, elles, s'affichent dans la liste.
- **Réglages en français dans AMP** : nom, liste officielle, description, site, langue (français),
  titre et message d'accueil (TeamKit + Discord, `\n` = retour à la ligne), joueurs max (32 au plus),
  manches, équipes, bots, vitesse, taille de l'arène. Le reste dans `perso.cfg`.
- **Console d'AMP branchée** (`SAY`, `KICK`, `BAN`, `PLAYERS`…), joueurs visibles dans AMP (arrivée,
  départ, changement de nom), arrêt propre (`QUIT`), bannissements gardés.
- **Testé en vrai** le 10 oct. 2026 dans un conteneur jetable, avec le **vrai client** 0.2.9.3.1 sous
  Xvfb : connexion, partie contre les bots, message d'accueil, accents, couleurs du nom. 8 Mo de RAM
  pour le serveur. Pas vérifié : l'apparition dans la liste Internet (port non ouvert pendant l'essai).
- **Ajouté le 11 oct. 2026** : 5 modes (classique, équipes, forteresse, zone de mort, sumo) tirés
  des exemples livrés avec le serveur ; 15 cartes vérifiées (5 livrées avec le jeu, les autres
  téléchargées toutes seules par les joueurs) en rotation au hasard ou dans l'ordre, toutes les
  N manches (le jeu n'a pas de rotation : c'est le lanceur qui la fait entre deux manches) ; bots
  réglables (jamais dans la liste des joueurs d'AMP) ; **votes** : `/vote include forteresse` ou
  `/vote include hexatron` dans le chat, les autres approuvent par Échap → Vote, `/help votes`
  donne la liste. Une instance créée avant garde son ancien formulaire et fonctionne exactement
  comme avant tant que le formulaire n'est pas mis à jour.
- Avant de pousser : `python verifier.py` doit répondre « Tout est bon. ».
