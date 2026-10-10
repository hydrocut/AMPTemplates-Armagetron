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

Invalid values (not a number, out of range, unknown language, URL starting with a quote) stop the
start with a French message naming the setting. Anything else goes in **`perso.cfg`**, read after
the AMP settings (so it can override them) and before the template's fixed lines.

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
| RAM | server 8.3 MB RSS (idle, and with 1 player + 3 bots playing), launcher 14 MB |
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
- Avant de pousser : `python verifier.py` doit répondre « Tout est bon. ».
