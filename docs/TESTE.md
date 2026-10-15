# Goblin Yapper test guide (from scratch)

> **Português:** este guia em português: [TESTE.pt-BR.md](TESTE.pt-BR.md).

This guide takes you from a computer with nothing installed to Goblin Yapper running, one step at a time. You
don't need to know how to program. Follow the steps in order and check the **"You should see"** of each one before
going on to the next. If something looks different, go to [Common problems](#common-problems).

Time: about 15 minutes, plus the download of the cloned voice if you want to try it (optional).

## What you need

- A computer with **Windows 10 or 11** (64-bit) and internet.
- About **1 GB of free disk space** for the basics.
- Only for the cloned voice (optional): about **13 GB free** and, preferably, an **NVIDIA** graphics card.
  Without an NVIDIA card the cloned voice works, but it is quite slow. You can test everything else with the
  Windows voice.

You do **not** need a Twitch account, or OBS, for the basic test.

---

## Step 1: install Python 3.13

Goblin Yapper is written in Python, so Python must be installed.

1. Open <https://www.python.org/downloads/windows/> in your browser.
2. In the list, look for **Python 3.13** and click **Windows installer (64-bit)** to download it.
3. Open the downloaded file.
4. **Important:** on the first screen, tick the box **"Add python.exe to PATH"**, at the bottom.
5. Click **Install Now** and wait for it to finish. Click **Close**.

Now check that it worked:

1. Press the **Windows** key, type `powershell` and press **Enter**. A blue or black window opens.
2. Type (or copy and paste) the command below and press **Enter**:

   ```powershell
   py -3.13 --version
   ```

**You should see:** `Python 3.13.` followed by a number, for example `Python 3.13.7`.

You can close that window.

---

## Step 2: download the project

1. Open this link in your browser. The download starts by itself:
   <https://github.com/NegentropyBeing/goblin-yapper/archive/refs/heads/main.zip>
2. Open the **Downloads** folder. Right-click the file `goblin-yapper-main.zip` and choose **Extract All...**
3. Under "Files will be extracted to this folder", delete what is written there and type `C:\` . Click
   **Extract**.

**You should see:** a folder `C:\goblin-yapper-main` with files like `README.md` and `requirements.txt` and
folders like `goblin_yapper` and `docs`.

If Windows won't let you extract to `C:\`, extract to the **Documents** folder. In that case, wherever this guide
says `C:\goblin-yapper-main`, use the `goblin-yapper-main` folder that ended up inside Documents.

---

## Step 3: open PowerShell inside the project folder

1. Open the folder `C:\goblin-yapper-main` in File Explorer.
2. Click the **address bar** at the top of the window (where the folder path is). The text becomes selected.
3. Type `powershell` and press **Enter**.

**You should see:** a PowerShell window whose last line ends with `C:\goblin-yapper-main>`.

All the commands in the next steps are typed **in that window**. To paste a copied command, right-click inside the
window.

---

## Step 4: install the dependencies

There are two commands. Run one at a time, waiting for the first to finish (the line `C:\goblin-yapper-main>`
shows up again) before running the second.

**Command 1** creates an isolated environment just for the project (about 20 seconds, it shows nothing on screen):

```powershell
py -3.13 -m venv .venv
```

**Command 2** downloads and installs the dependencies (up to 1 minute):

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
```

**You should see:** several download lines and, near the end, a line that starts with `Successfully installed`.
A `[notice] A new release of pip is available` warning is normal, you can ignore it.

You don't need to "activate" the environment or install anything else. This is done only once.

---

## Step 5: start Goblin Yapper

In the same window, run:

```powershell
.venv\Scripts\python -m goblin_yapper
```

**You should see**, within a few seconds, a list of commands and lines like these:

```
config created at C:\goblin-yapper-main\config.toml
panel: http://127.0.0.1:8765/panel  |  overlay: http://127.0.0.1:8765/overlay
no Twitch channel set (use the panel or: channel <channel>)
>
```

The warning about the Twitch channel and a `voice server not installed` warning are normal at this stage.

**Leave that window open.** It is the program running. If you close the window, Goblin Yapper stops.

---

## Step 6: open the panel

Open your browser (Chrome or Edge) and go to this address:

<http://127.0.0.1:8765/panel>

**You should see:** a dark screen with the title **Goblin Yapper**, the **Goblin** and **Voice** tabs, a **Queue**
column and colored team columns, each with a goblin.

The panel opens in your Windows language. If it appears in a language you don't want, change it with **Language**
at the top right.

This address only works on your own computer and only while the window from Step 5 is open.

---

## Step 7: choose the voice

Click the **Voice** tab. Choose **one** of the options.

### Option A: Windows voice (fast, recommended to start)

1. At the top right, under **engine**, choose **Windows (SAPI)**.

That's it. The yellow warning about the voice server can be ignored with this option.

### Option B: cloned voice (OmniVoice)

Only do this if you have the ~13 GB free. It takes a while the first time.

1. Under **engine**, leave **OmniVoice (server)**.
2. In the yellow warning, click **Install voice server**.
3. Wait. The screen shows the progress in 5 steps. It is about 3.5 GB of download, 5 to 20 minutes depending on
   your internet. Don't close anything.
4. When it finishes, the text at the top changes to **loading the voice model…** and downloads ~3 GB more. Wait
   until **OmniVoice · ready** shows up with a green dot.

To clone a voice, you need a `.wav` file with 3 to 20 seconds of clean speech. **Only use someone's voice with
their permission.**

1. Drag the `.wav` to the **Drop a .wav here** area.
2. Wait for the **Prepare audio** and **Transcribe** steps to get a green ✓. The first time, the transcription
   downloads ~1.6 GB more and can take a few minutes; the next times it takes seconds.
3. Check that the text under **Transcript** is exactly what is said in the audio. Fix it if you need to.
4. Give it a name and click **Create profile**.
5. Under **Each team's voice**, pick that profile for the teams.
6. Under **Test speech**, click **Speak** to listen.

---

## Step 8: test script

Go back to the **Goblin** tab. You can test everything without Twitch, adding names by hand.

**Teams**

1. In the **add a nick** field, at the bottom of the **Queue** column, type `ana` and press **Enter**. Repeat
   with `bia`, `caio` and `duda`. → The four names show up in the Queue.
2. Next to **teams**, click **2**. → Only the Blue and Green columns are left.
3. Click **Sort**. → Two names in each team, the Queue is empty.
4. Drag a name from one team to the other. → The name changes column.
5. Click **Re-sort**, then **Return to queue**. → The teams change; then everyone goes back to the Queue.
   Click **Sort** again to go on.

**Voice**

6. On a team, click **🔊 Test voice**. → You hear "Hey chat! This is the … team's goblin." and that team's goblin
   moves while it talks. The other team's goblin stays still.
7. Click **🎤 Draw voice** on the Blue team. → A card with the drawn name appears at the top, and the name is
   highlighted in the column.
8. Click **⏭ Next**. → The voice goes to the other person on the same team.
9. Tick **several teams at the same time** and click **🎤 Draw voice** on the Green team. → Two cards at the
   top, one from each team.
10. Click **⏹ Stop** on the Blue team. → Only the Blue card goes away. Then click **Stop voice**, at the top.
    → The other card goes away and "nobody has the voice" shows up.

**Look**

11. On a team, change the color under **tint** and drag the bar next to it. → That team's goblin changes color
    right away.
12. Click **OBS overlay and goblin images**, at the bottom, and click **copy** next to **Team blue**. Open a
    **new window** of the browser (Ctrl+N), paste the address and press **Enter**. Click once inside that window
    (this unlocks the sound) and leave it visible next to the panel. In the panel, click **🔊 Test voice** on
    Blue. → The goblin in the new window moves and the sound comes from it, and a green dot shows up next to the
    **Team blue** URL in the panel.

**With Twitch (optional)**

13. In the **twitch channel** field, type a channel name and click **Connect**. → `#channel · connected` shows
    up with a green dot.
14. Click **Open queue** and, in that channel's chat, type `!joinsort`. → Your nick shows up in the Queue.
15. Hover over your nick and click the 🎤 that appears next to it. Then write anything in the chat. → The
    message is read aloud.

---

## Closing and opening again

- **To close:** in the PowerShell window, type `quit` and press **Enter** (or just close the window).
- **To open again:** repeat only steps **3**, **5** and **6**. Steps 1, 2 and 4 are done only once.

Your settings are kept in the project folder and come back when you open it again.

---

## Common problems

| What shows up | What to do |
|---|---|
| `py : The term 'py' is not recognized` | Python was not installed, or the PowerShell window is old. Close the window, redo Step 1 (ticking **Add python.exe to PATH**) and open a new window. |
| `Python 3.13 not found` or `No suitable Python runtime found` | Another Python version is installed, but not 3.13. Install 3.13 from Step 1; they live together without trouble. |
| `Cannot find path` or `requirements.txt` not found | PowerShell is not in the project folder. Close it and redo Step 3. The last line must end with `goblin-yapper-main>`. |
| `error while attempting to bind on address ('127.0.0.1', 8765)` | Goblin Yapper is already open in another window. Close the other window (or the installed app) and run Step 5 again. |
| The browser says **"This site can't be reached"** | The window from Step 5 was closed or hit an error. Look at the PowerShell window and run Step 5 again. |
| `running scripts is disabled on this system` | You tried to "activate" the environment. You don't need to: use the commands exactly as they are in this guide. |
| Red error in Step 4, command 2 | Almost always the internet. Check your connection and run the command again. |
| No sound | Check the computer's volume. In the **Voice** tab, see whether **engine** is **Windows (SAPI)** or the top shows **OmniVoice · ready**. If you opened the overlay in a tab, click once inside it. |
| The voice installation failed | Click **Try again**. Check the disk space (~13 GB) and the internet. |
| The screen shows **"connecting to the server…"** | The window from Step 5 was closed. Run Step 5 again; the page comes back by itself. |

## How to report a problem

Send the person who asked for the test:

1. What you did, step by step, and what you expected to happen.
2. A screenshot of the panel and of the PowerShell window.
3. The file `goblin-yapper.log`, which is in `C:\goblin-yapper-main`. If the problem is with the cloned voice,
   also send `C:\goblin-yapper-main\tts\tts-server.log`.

## To delete everything afterwards

1. Close Goblin Yapper and delete the folder `C:\goblin-yapper-main`.
2. If you installed the cloned voice: press **Windows + R**, type `%LOCALAPPDATA%` and press **Enter**; delete
   the `GoblinYapper` folder. To also delete the voice model, press **Windows + R**, type
   `%USERPROFILE%\.cache\huggingface` and delete the `hub` folder. Careful: that `hub` folder also holds the
   models of other AI programs, if you have any.
3. Python can be removed in **Settings → Apps**, if you won't use it for anything else.
