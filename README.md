# Computer Time Notifier

Shows Windows toast notifications telling a child how much computer time they have left
today, based on the limits set in [Microsoft Family Safety](https://family.microsoft.com/).

It checks Family Safety on a schedule and notifies once when it starts (with the exact
time left), then again each time the remaining time drops past a configured threshold
(for example 4 hours, 3 hours, 2 hours and 30 minutes). If extra time is granted or the
allowance resets on a new day, the thresholds re-arm.

## Requirements

- Windows 10 or 11 (notifications use Windows toasts, and the login is stored in
  Windows Credential Manager)
- Python 3.12 or newer
- A Microsoft **parent/organizer** account in a Family Safety family group
- A child account in that family with a daily **Windows** screen-time limit set
  (Family Safety → the child → Screen time → Windows). On days with no Windows limit,
  no notifications are shown.

## Setup

### 1. Get the code and install it

```powershell
git clone https://github.com/ThisIsDifficult42/computertimetracker.git
cd computertimetracker
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

Tthe app reads `config.toml` and writes its log file in the project folder, which it finds relative to the installed source.

The `pyfamilysafety` dependency is installed from a
[fork](https://github.com/ThisIsDifficult42/pyfamilysafety) that adds support for reading
device limit schedules, so `pip` needs internet access to GitHub.

### 2. Edit `config.toml`

```toml
# First name of the family member to monitor, as shown in Microsoft Family Safety.
memberName = "Alex"

# How often to check Family Safety, in minutes (minimum 1; 5 or more recommended).
pollIntervalMinutes = 5

# Show a notification when this many minutes of computer time are left.
alertThresholdsMinutes = [240, 180, 120, 30]
```

| Setting                  | Meaning                                                                                      |
| ------------------------ | -------------------------------------------------------------------------------------------- |
| `memberName`             | The child's first name exactly as Family Safety shows it (case doesn't matter). Must match exactly one family member. |
| `pollIntervalMinutes`    | Minutes between checks. Values below 1 are raised to 1. Family Safety's usage figures lag, so very short intervals don't add accuracy. |
| `alertThresholdsMinutes` | Whole minutes of time left that trigger a notification. Order doesn't matter.                |

### 3. Sign in to Family Safety

```powershell
python -m computertimenotifier login
```

1. Open the URL it prints and sign in with the **parent's** Microsoft account.
2. You'll end up on a blank page with a warning saying that Microsoft wouldn't need you to copy and paste the URL. That warning is normally something you should follow, but the information in the URL is needed to log in as your user and query Family Services.
3. Quickly copy the full URL from the address bar (it starts with `https://login.live.com/oauth20_desktop.srf?code=...`) and paste it into the prompt. This is only used for accessing Microsoft Family Services and nothing else.

The resulting refresh token is stored in Windows Credential Manager (under
`computertimenotifier`), not in the project folder. If the login later expires, a
notification will tell you to run `login` again.

#### Why am I copying the URL when the webpage says I shouldn't?
The URL is used in a lot of phishing attacks because it can let anyone access Microsoft services on your behalf with the right setup. The token in the URL is scoped only to Microsoft Family services to limit any impact (set in the pyfamilysafety library). Future versions of the app will attempt to fix this message (if possible).

### 4. Check that notifications work

```powershell
python -m computertimenotifier demo
```

This shows every notification your thresholds would produce, 5 seconds apart. If nothing
appears, check that notifications are enabled in Windows Settings → System →
Notifications, and that Focus / Do Not Disturb is off.

## Running

```powershell
python -m computertimenotifier
```

(`run` is the default command.) It keeps running until stopped with Ctrl+C. Use
`--config path\to\file.toml` to use a different config file.

Logs go to the console and to `computertimenotifier.log` in the project folder (rotated
at 1 MB, keeping two old files). Network errors are retried on the next check; after
more than 3 failures in a row, each further failure also shows a notification.

### Start automatically at sign-in

To run it in the background on the child's account without a console window, use
`pythonw.exe` from the virtual environment. For example, create a shortcut in the child's
Startup folder (`Win+R` → `shell:startup`) with the target:

```text
C:\path\to\computertimetracker\.venv\Scripts\pythonw.exe -m computertimenotifier
```

and set **Start in** to `C:\path\to\computertimetracker`. Alternatively, create a Task
Scheduler task that runs the same command "At log on" for that user.

Run the `login` step while signed in as the same Windows user that will run the
notifier, since Credential Manager entries are per user.

## Development

```powershell
pip install -e ".[dev]"
pytest
ruff check .
```

## Disclaimer

This project uses an unofficial Family Safety API via `pyfamilysafety`. It is not
affiliated with or endorsed by Microsoft, and it may stop working if Microsoft changes
the service.
