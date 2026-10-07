# Soundpad
![Python](https://img.shields.io/badge/python-3670A0.svg?style=for-the-badge&logo=python&logoColor=ffdd54)

Soundboard for Windows 10 and 11. It runs in the terminal and keeps working in the background. Your sounds play
into a virtual microphone cable, so Discord, games and OBS hear them, and on your speakers so you hear them too.
A key or key combination triggers a sound in any window, also in a fullscreen game.

The voice changer is a separate project, [Voicer](https://github.com/4ourself/voicer). Both can use the same
cable at the same time.

![Title screen](docs/screenshots/15_title_screen_logo_glow.png)

![Sounds screen](docs/screenshots/05_after_loading.png)

## Install

Needs Windows 10 or 11 and Python 3.10 or newer ([python.org](https://www.python.org/downloads/), tick
"Add python.exe to PATH").

1. Download the repository (Code, Download ZIP) and unpack it.
2. Double-click **run.bat**.

`run.bat` creates a private `.venv` folder once, installs the libraries only if they are missing, and starts
`main.py`. A normal launch downloads nothing.

Manual start: `pip install -r requirements.txt`, then `python main.py`. Use Windows Terminal, at least 80x24.

## Setup

Soundpad needs two devices. No microphone, no voice effects.

1. Install a virtual cable, for example [VB-Cable](https://vb-audio.com/Cable/).
2. Start Soundpad, press Enter on the title screen. The first run opens a setup screen with the cable and your
   default speakers preselected. Choose **FINISH SETUP**.
3. In Discord, OBS or the game choose `CABLE Output` as the microphone. Turn off automatic input sensitivity.

![Devices](docs/screenshots/14_devices.png)

| Device | Meaning |
|--------|---------|
| Output | the virtual cable (`CABLE Input`) |
| Speaker | your headphones or speakers |

## Controls

| Key | Action |
|-----|--------|
| Up / Down | move |
| Left / Right | change a value, Right opens a sound's editor |
| Enter | switch on or off, confirm, play the selected sound |
| Backspace | go back |

Hold Left or Right to change sliders faster.

## Loading sounds

Sounds, then **+ Load folder or file**. Paste a path and press Enter. The field says FOLDER, FILE or NOT FOUND
while you type. Quotes from "Copy as path" are fine, Tab completes paths.

<img src="docs/screenshots/04_load_prompt_pasted_path.png" width="49%"> <img src="docs/screenshots/05_after_loading.png" width="49%">

- A folder loads all audio files in it and its subfolders (can be turned off in Settings).
- All common audio formats work: wav, mp3, ogg, opus, flac, aiff, m4a, aac, wma, webm and audio in mp4 or mkv.
- Loaded folders are scanned again at every start. New files appear, your keys and volumes stay.
- Long files are streamed from disk. Everything else is decoded at start for instant playback.

## Sounds screen

One row per sound with key, volume and state. Enter plays it. **Stop all sounds** fades everything out.
On the right: details, the live KEYS panel, levels with a waveform, and playback progress.

![Sounds with the keys panel](docs/screenshots/02_sounds_keys_panel.png)

It also fits the minimum size of 80x24.

![Sounds at 80x24](docs/screenshots/03_sounds_80x24.png)

## Keys

Soundpad listens to all key presses system-wide, so sounds work while you are in a game or another program.

- A single key (`F7`, `NUM1`, `ALT`) or a combination (`CTRL+ALT+S`).
- Keys are never blocked. Windows and the game still get every key press.
- **Set a key:** open the sound's editor with Right, select **Key**, press Enter, press the key.
- **Remove a key:** select **Key**, press Enter, then Enter or Backspace again. It shows `[ none ]`.
  Escape cancels. Because of this, Enter or Backspace alone cannot be a sound key, `CTRL+ENTER` can.
- **Backspace** in the editor saves your changes and goes back. **CANCEL** discards them.
- A **Stop-all key** fades out everything. **Repeat while held** retriggers a held key.
- A sound on `ALT` plays when Alt goes down, so Alt+F4 plays it too. Turn on Settings > Keyboard >
  "Single keys ignore modifiers" to avoid that.

![Recording a key](docs/screenshots/07_recording_a_key.png)

## Sound editor

Name, Key, Volume (0 to 200 percent), Cooldown, Remove. Removing asks first and never deletes the file.

<img src="docs/screenshots/06_edit_sound.png" width="49%"> <img src="docs/screenshots/08_remove_dialog.png" width="49%">

## Settings

| Page | Contains |
|------|----------|
| Audio | hear sounds on the speaker, master volume, speaker volume |
| Devices | output, speaker, refresh, audio system |
| Sounds | maximum sounds at once, overlap, default cooldown, subfolders, loaded folders, preload |
| Keyboard | stop-all key, single keys ignore modifiers, repeat while held, hook status |
| Performance | buffer 10 to 40 ms, sample rate, estimated latency |
| Interface | characters, refresh rate |
| Config | export and import |

<img src="docs/screenshots/09_settings_audio.png" width="32%"> <img src="docs/screenshots/10_settings_sounds.png" width="32%"> <img src="docs/screenshots/11_settings_keyboard.png" width="32%">

## Help and signal check

**Signal check** follows a sound through the chain and says where it stops: output not open, a normal device
instead of a cable, speaker missing, key hook not running, sounds that cannot be decoded, volume at 0.

<img src="docs/screenshots/12_help_overview.png" width="49%"> <img src="docs/screenshots/13_help_signal_check.png" width="49%">

## Customize

In the main menu. Everything applies at once and is saved.

![Main menu](docs/screenshots/18_main_menu_has_customize.png)

![Customize](docs/screenshots/20_customize_colors.png)

### Colors

Main color and volume graph colors can be a solid color, a gradient of 2 to 4 colors, or animated rainbow.
Controls: hue, saturation, brightness, RGB, hex and alpha.

<img src="docs/screenshots/21_editor_solid_color.png" width="49%"> <img src="docs/screenshots/22_editor_gradient.png" width="49%">
<img src="docs/screenshots/25_editor_graph_gradient.png" width="49%"> <img src="docs/screenshots/27_editor_rainbow.png" width="49%">
<img src="docs/screenshots/24_custom_gradient_ui_and_graph.png" width="49%"> <img src="docs/screenshots/26_rainbow_mode.png" width="49%">

### Backdrop and blur

| Backdrop | Result |
|----------|--------|
| terminal | nothing is painted, the Windows Terminal blur stays (default) |
| glass | your color is laid over the blur, alpha sets how much of the blur shows |
| custom | solid painted background, hides the blur |

A terminal cannot mix a cell color with the desktop, so `glass` uses shade characters to let the blur show
between them. If gradients look banded, set Color mode to `true`.

<img src="docs/screenshots/glass_backdrop_gradient.png" width="49%"> <img src="docs/screenshots/glass_backdrop_alpha_editor.png" width="49%">
<img src="docs/screenshots/23_editor_alpha_see_through.png" width="49%"> <img src="docs/screenshots/28_backdrop_gradient_with_alpha.png" width="49%">
<img src="docs/screenshots/29_editor_backdrop.png" width="49%">

The screenshots have no real blur behind them.

### Layout

Graph position and menu position: left, center or right. Borders: rounded or square.

<img src="docs/screenshots/30_graph_left.png" width="49%"> <img src="docs/screenshots/31_graph_center.png" width="49%">
<img src="docs/screenshots/32_menu_right.png" width="49%"> <img src="docs/screenshots/34_customize_layout.png" width="49%">

### Animation

Tab animation: none (default), fade, line, slide, wipe, dissolve, curtain, blinds, random. It only affects
the screen, never the audio.

![Animation settings](docs/screenshots/35_customize_animation.png)

<details>
<summary>Animation frames</summary>

<img src="docs/screenshots/39_animation_fade.png" width="49%"> <img src="docs/screenshots/40_animation_line.png" width="49%">
<img src="docs/screenshots/41_animation_slide.png" width="49%"> <img src="docs/screenshots/42_animation_wipe.png" width="49%">
<img src="docs/screenshots/43_animation_dissolve.png" width="49%"> <img src="docs/screenshots/44_animation_curtain.png" width="49%">
<img src="docs/screenshots/45_animation_blinds.png" width="49%">

</details>

### Logo

Title screen on or off, logo glow: sometimes, always or off.

<img src="docs/screenshots/16_title_screen_gradient.png" width="49%"> <img src="docs/screenshots/17_title_screen_rainbow.png" width="49%">
<img src="docs/screenshots/19_title_screen_80x24.png" width="49%"> <img src="docs/screenshots/36_customize_logo.png" width="49%">

### Config export and import

Customize > Config. Export saves your look and settings to one JSON file, import loads it. Soundpad and Voicer
share the format, so a look made in one works in the other. Audio devices, loaded folders and sound keys are
never included.

<img src="docs/screenshots/37_customize_config_import_export.png" width="49%"> <img src="docs/screenshots/38_export_config_prompt.png" width="49%">

## Use with Voicer

Select the same cable as Output in both programs. Windows mixes the two, so Discord hears your voice and your
sounds. Sounds never pass through the voice effects.

## Loud sounds

A look-ahead limiter on the output turns very loud sounds down smoothly instead of clipping them. It adds about
1.5 ms of delay. If a loud sound still sounds cut in Discord, turn off Noise Suppression, Echo Cancellation
and Automatic Gain Control in Discord (User Settings, Voice and Video), they are made for speech.

## Troubleshooting

- **Text from a decoder, or a file does not play.** A damaged file is played as far as it can be decoded. Details
  are in `data/decoder.log`. A file that cannot be read at all shows as an error in the list.
- **No sound in Discord.** Open Help, Signal check. It says where the sound stops.

## Privacy

Soundpad has to see every key press to know when to play a sound. What it does with them:

- Each key is compared with your bindings in memory, nothing else.
- The last 12 presses are kept in memory for the KEYS panel and never written to disk.
- No network code, no telemetry, no update check. Only `pip` downloads the libraries, once.
- Keys are not blocked, changed or injected.
- It writes only to its `data` folder and to files you export.

The whole keyboard side is one file: `soundpad/keybinds.py`.

## Command line

```
python main.py                 start
python main.py --list-devices  list output devices and exit
```

`SOUNDPAD_DATA` changes the data folder.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest -q tests
```

Tests use a fake audio backend and simulated key events, no sound hardware needed.

## License

MIT, see [LICENSE](LICENSE). The logo uses the "Bloody" FIGlet font.
