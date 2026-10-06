# Soundpad

A soundboard for Windows 10 and 11 that runs in a terminal window and keeps working in the background.
It plays your sounds into a virtual microphone cable, so Discord, games or OBS hear them, and also on your own
speakers or headphones so you hear them too. A sound is triggered by a key or a key combination, in any
window, whether Soundpad is focused, minimized or you are in a fullscreen game.

Soundpad needs two devices and nothing else. No microphone, no voice effects.

| Device  | What it is |
|---------|------------|
| Output  | the virtual cable that acts as your microphone, for example `CABLE Input` from VB-Cable |
| Speaker | your headphones or speakers |

The voice changer is a separate project, [Voicer](../voicer_GIT). The two can run at the same time and share
one cable (see "Using it with Voicer" below).

![Soundpad title screen](docs/screenshots/15_title_screen_logo_glow.png)

![Sounds screen](docs/screenshots/05_after_loading.png)

## Contents

- [Install and run](#install-and-run)
- [First start and the virtual cable](#first-start-and-the-virtual-cable)
- [Loading sounds](#loading-sounds)
- [Keys](#keys)
- [Controls](#controls)
- [Screens](#screens)
- [Customize](#customize)
- [Config files](#config-files)
- [Using it with Voicer](#using-it-with-voicer)
- [Privacy and safety](#privacy-and-safety)
- [Command line](#command-line)
- [Data files](#data-files)
- [How it works](#how-it-works)
- [Tests](#tests)
- [License](#license)

## Install and run

You need Windows 10 or 11 and Python 3.10 or newer ([python.org](https://www.python.org/downloads/), tick
"Add python.exe to PATH" in the installer).

Download the repository (Code, then Download ZIP, or `git clone`), then double-click **run.bat**.

What `run.bat` does:

1. Finds Python.
2. Creates a private environment in the `.venv` folder next to it (once). Nothing is installed system-wide.
3. Checks that the libraries are present. Only if one is missing it runs `pip install -r requirements.txt`.
   A normal launch downloads nothing.
4. Starts `main.py`.

Manual start, if you prefer:

```
pip install -r requirements.txt
python main.py
```

Use Windows Terminal if you can (the default terminal on Windows 11). The window must be at least 80 by 24
characters. Truecolor is detected automatically; other consoles fall back to 256 or 16 colors.

Libraries: numpy, sounddevice, soundfile, soxr, av (PyAV) and pynput. Their licenses are their own.

## First start and the virtual cable

1. Install a virtual cable such as [VB-Cable](https://vb-audio.com/Cable/).
2. Start Soundpad and press Enter on the title screen. On the very first run a setup screen opens. It
   preselects the cable as Output and your default device as Speaker. Move to **FINISH SETUP** and press Enter.
3. In Discord (or the game, or OBS) choose `CABLE Output` as the input device and turn off
   "Automatic input sensitivity", otherwise Discord may cut the start of short sounds.

![First start device list](docs/screenshots/14_devices.png)

The device screen can be opened again from Settings > Devices. It shows each device with its state, sample
rate and whether it looks like a virtual cable.

## Loading sounds

Open **Sounds**, select **+ Load folder or file**, paste a path and press Enter. The field shows FOLDER, FILE or
NOT FOUND while you type. Quotes around the path (Explorer's "Copy as path") are fine, and Tab completes paths.

![Load prompt](docs/screenshots/04_load_prompt_pasted_path.png)

- A folder loads every audio file in it and in the folders inside it. Switch that off with
  Settings > Sounds > Include subfolders. A single file works too.
- All audio formats are accepted: wav, mp3, ogg, opus, flac, aiff, m4a, aac, wma, webm, audio in mp4 or mkv and
  more. libsndfile decodes the common ones, PyAV (which bundles ffmpeg) decodes the rest. A file with an unknown
  extension is probed and used if it contains audio. Images, text files and so on are ignored.
- Loaded folders are scanned again at every start. New files show up without a key, existing keys, volumes and
  names stay. A sound you removed stays removed until you load its folder again.
- Files longer than two minutes are streamed from disk instead of being kept in memory.
- With **Preload sounds** on (default) everything is decoded at start for instant playback.

## Keys

Soundpad installs a global keyboard hook when it starts and removes it when you quit.

- A single key works: `F7`, `NUM1`, `ALT`.
- Combinations work: `CTRL+ALT+S`.
- Keys are never blocked or swallowed. The hook only listens, Windows and the game still get every key.
  A sound bound to `ALT` plays the moment Alt goes down, so Alt+F4 still closes the window and also plays that
  sound. If you do not want that, turn on Settings > Keyboard > "Single keys ignore modifiers": a lone `ALT`
  then fires only when no other key is held.
- To set a key: select a sound, press Right to open its editor, select **Key**, press Enter and press the key
  or combination. Left clears the key. Escape cancels while waiting for a key.
- A global **Stop-all key** (Settings > Keyboard) fades out everything that is playing.
- **Repeat while held** makes a held key retrigger the sound, limited by the cooldown.
- The **KEYS** panel on the Sounds screen is a live view: the keys held right now and the last presses, with
  the sound each one triggered.

![Recording a key](docs/screenshots/07_recording_a_key.png)

## Controls

Only a few keys are used everywhere.

| Key | Action |
|-----|--------|
| Up / Down | move |
| Left / Right | adjust a slider or choice, open or close a sound's editor |
| Enter | activate or toggle (on a sound: play it) |
| Backspace | go back, from the home menu it asks to quit |

Holding Left or Right speeds up sliders the longer you hold. In text fields Backspace deletes characters.

## Screens

**Title screen and home menu.** The logo glows from time to time. Press Enter to reach the menu: Sounds,
Customize, Settings, Help & diagnostics, Exit. Before the menu is usable the home screen shows the start-up
steps (config, devices, audio, sounds, keyboard hook) with their state.

![Main menu](docs/screenshots/18_main_menu_has_customize.png)

**Sounds.** One row per sound with its key, volume and state (READY or PLAYING). Enter plays the sound, **Stop
all sounds** fades everything out. To the right: details of the selected sound, the KEYS panel, the LEVELS panel
(Output and Speaker meters plus a waveform of what is being sent) and PLAYBACK with progress of the running sounds.

![Sounds with the keys panel](docs/screenshots/02_sounds_keys_panel.png)

It also works at the minimum size of 80 by 24:

![Sounds at 80x24](docs/screenshots/03_sounds_80x24.png)

**Sound editor.** Right on a sound opens it: Name, Key, Volume (0 to 200 percent), Cooldown (minimum time
between two triggers of that sound) and Remove. Removing asks first and never deletes the file.

![Editing a sound](docs/screenshots/06_edit_sound.png)

![Remove dialog](docs/screenshots/08_remove_dialog.png)

**Settings.**

- Audio: hear sounds on the speaker, master volume (everything sent to the Output), speaker volume.
- Devices: Output, Speaker, refresh devices, audio system (WASAPI by default).
- Sounds: maximum simultaneous sounds, overlapping sounds on or off, default cooldown, include subfolders,
  loaded folders (rescan, forget), preload.
- Keyboard: stop-all key, single keys ignore modifiers, repeat while held, status of the global listener.
- Performance: audio buffer (10 to 40 ms), safety buffer, sample rate, estimated latency.
- Interface: characters (unicode or ASCII), refresh rate.
- Config: export and import, see below.

![Settings audio](docs/screenshots/09_settings_audio.png)
![Settings sounds](docs/screenshots/10_settings_sounds.png)
![Settings keyboard](docs/screenshots/11_settings_keyboard.png)

**Help.** Three pages. Overview explains the setup. **Signal check** follows a sound through the chain and tells
where it stops: Output not open, Output is a normal device instead of a cable, Speaker missing, "Hear sounds"
off, key hook not running, no sounds or no keys yet, sounds that cannot be decoded, master volume at 0, buffer
underruns. The event
log lists what happened since the start.

![Help overview](docs/screenshots/12_help_overview.png)
![Signal check](docs/screenshots/13_help_signal_check.png)

## Customize

Customize is in the main menu and in the header. Everything applies immediately and is saved.

![Customize](docs/screenshots/20_customize_colors.png)

**Colors**

- **Main color**: the color of focus bars, titles and borders. The editor has three columns. Controls on the
  left (mode, color stops, hue, saturation, brightness, red, green, blue, hex, alpha, reset), a color field and
  hue strip in the middle, and a live example on the right. Modes are Solid, Gradient (2 to 4 colors) and
  Rainbow (animated, with a speed).
- **Main color preset**: cyan, green, magenta, amber, blue or custom.
- **Volume graph colors**: meters and waveform. Same editor plus Zones (the default green, yellow, red).
- **Backdrop** and **Backdrop color**: see the note on alpha below.
- **Reset colors** and **Color mode** (auto, true, 256, 16, mono).

![Solid color editor](docs/screenshots/21_editor_solid_color.png)
![Gradient editor](docs/screenshots/22_editor_gradient.png)
![Graph colors](docs/screenshots/25_editor_graph_gradient.png)
![Rainbow editor](docs/screenshots/27_editor_rainbow.png)

A UI with a gradient and a gradient volume graph, and rainbow mode:

![Gradient UI](docs/screenshots/24_custom_gradient_ui_and_graph.png)
![Rainbow UI](docs/screenshots/26_rainbow_mode.png)

**About alpha.** A terminal cannot show your desktop through single characters, so alpha cannot be real
transparency per cell. Alpha mixes a color with the **Backdrop**. With Backdrop set to `terminal` (default) that
is the terminal's own background, assumed to be near black. With `custom` you paint a solid color or a vertical
gradient, the app fills its background with it, and alpha blends against that. If you want real see-through,
use Windows Terminal's own opacity or acrylic setting and keep Backdrop on `terminal`.

![Alpha in the editor](docs/screenshots/23_editor_alpha_see_through.png)
![Custom backdrop](docs/screenshots/28_backdrop_gradient_with_alpha.png)
![Backdrop editor](docs/screenshots/29_editor_backdrop.png)

**Layout**

- Graph position: left, center or right (center needs about 112 columns, otherwise it falls back to right).
- Menu position: left, center or right.
- Borders: rounded (default) or square.

![Graph left](docs/screenshots/30_graph_left.png)
![Graph center](docs/screenshots/31_graph_center.png)
![Menu right](docs/screenshots/32_menu_right.png)
![Layout page](docs/screenshots/34_customize_layout.png)

**Animation.** Tab animation: none (default), fade, line, slide, wipe, dissolve, curtain, blinds or random, with
speed fast, normal or slow. Choosing one plays it once. Animations only touch the screen, never the audio.

![Animation page](docs/screenshots/35_customize_animation.png)

<details>
<summary>Animation frames</summary>

![fade](docs/screenshots/39_animation_fade.png)
![line](docs/screenshots/40_animation_line.png)
![slide](docs/screenshots/41_animation_slide.png)
![wipe](docs/screenshots/42_animation_wipe.png)
![dissolve](docs/screenshots/43_animation_dissolve.png)
![curtain](docs/screenshots/44_animation_curtain.png)
![blinds](docs/screenshots/45_animation_blinds.png)

</details>

**Logo.** Title screen on or off, and logo glow: sometimes (default), always or off.

![Logo with a gradient](docs/screenshots/16_title_screen_gradient.png)
![Logo with rainbow](docs/screenshots/17_title_screen_rainbow.png)
![Title screen at 80x24](docs/screenshots/19_title_screen_80x24.png)
![Logo page](docs/screenshots/36_customize_logo.png)

## Config files

Customize > Config (also Settings > Config) has **Export config** and **Import config**. Export writes your
colors and settings to one JSON file, import reads one and applies it right away. Soundpad and Voicer use the
same format, so a look made in one can be imported in the other. The default file name is
`voicer-soundpad-config.json` in your user folder, so moving a look between the programs is Enter, Enter.

![Config page](docs/screenshots/37_customize_config_import_export.png)
![Export prompt](docs/screenshots/38_export_config_prompt.png)

Included: colors, layout, borders, animation, title screen and logo, characters, refresh rate, audio buffers
and each program's own tuning (volumes, the hear switch, cooldown, overlap and key behavior).

Never included: audio devices, the audio system, loaded folders, sounds, key bindings of single sounds. Importing
never changes your devices. Settings the other program does not have are skipped, and every value is checked
before it is stored, so a damaged or hand-edited file cannot break the app. A plain `data/config.json` can be
imported as well.

## Using it with Voicer

Both programs can write to the same virtual cable. Windows mixes the streams, so Discord hears your changed
voice from Voicer and your sounds from Soundpad. Sounds never pass through Voicer's effects. Select the same
cable as Output in both and do not use the cable's recording side (`CABLE Output`) as the input of either.

## Privacy and safety

Soundpad has to see every key press to know when a sound should play. That is what a global hook is, so here
is exactly what it does with them:

- The key is compared with your bindings in memory. Nothing else is done with it.
- The last 12 presses are kept in memory only to draw the KEYS panel. They are never written to disk.
- There is no network code in the program. It does not send anything anywhere, has no telemetry and no update
  check. You can verify this: the source is small and `grep -r "socket\|urllib\|http" .` finds nothing in the
  program code.
- Keys are not blocked, modified or injected.
- The only places it writes to are its own `data` folder (settings and the sound list) and files you export.
- The one network use is `pip` downloading the libraries from PyPI, once, in `run.bat` or when you install
  them yourself.
- If ffmpeg is on your PATH it may be called to decode an unusual file that PyAV cannot read. Nothing else
  starts other programs.

If you do not trust a build, read the code: `soundpad/keybinds.py` is the whole keyboard side.

## Command line

```
python main.py                 start the interface
python main.py --list-devices  print the output devices and exit
```

The environment variable `SOUNDPAD_DATA` moves the data folder.

## Data files

Created in `data/` next to the program (ignored by git): `config.json` (settings, devices) and `sounds.json`
(your sound list with keys, volumes and names).

## How it works

```
main.py                 entry point
config.py               data/config.json, atomic and debounced saves
configfile.py           config export and import
controller.py           what the UI talks to
audio/                  engine, devices, output stream, ring buffer, meters, limiter, diagnostics
soundpad/loader.py      decoding, folder scan, format probing, streaming
soundpad/player.py      many simultaneous voices, fade out on stop
soundpad/keybinds.py    global hook, combination matching, held keys and history
soundpad/manager.py     library, worker thread, load and rescan
ui/                     terminal renderer, theme, colors, animations, widgets, dialogs, screens
tests/                  automated tests
```

- The Output callback is the audio clock. If the Output device is missing or unplugged, the Speaker stream takes
  over so the pad still works on speakers alone. A watchdog reconnects lost devices.
- Audio callbacks use 10 ms blocks and only light numpy work. The key hook only puts events in a queue, a worker
  thread applies cooldowns, decodes lazily and starts playback. The interface runs at 30 frames per second
  through a diff renderer and never touches audio buffers, so a slow terminal cannot cause crackling.
- A soft limiter keeps overlapping sounds below clipping.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest -q tests
```

The tests use a fake audio backend and simulated key events, so they need no sound hardware. They cannot
cover the real Windows key hook, the Windows console input or a real virtual cable; those were only run by hand.

## License

MIT, see [LICENSE](LICENSE). The logo is set in the "Bloody" FIGlet font.
