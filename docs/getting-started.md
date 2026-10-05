# Getting started

## Installation

Download the installer for your system from GitHub Releases (Windows setup `.exe`, macOS `.dmg` for
Apple Silicon or Intel, Linux `.AppImage` or `.deb`). No Python, Rust or administrator rights are needed.

> **Pre-release notice.** PropBench is developed by one person and the installers are **not yet code-signed**.
> Your system will warn you the first time you open it. This is expected; approve it once as described below.
> To verify a download, compare its SHA-256 checksum with the one published on the release page.

### macOS (Apple Silicon or Intel)
1. Open the `.dmg` and drag **PropBench** into **Applications**.
2. Open PropBench. macOS says it *cannot verify the developer* and offers only **Done** or **Move to Trash**. Choose **Done**.
3. Open **System Settings › Privacy & Security**, scroll to **Security**, and click **Open Anyway** next to the
   PropBench message. Enter your password if asked.
4. Open PropBench again and confirm **Open**. macOS remembers this; you only do it once per version.

*Advanced alternative (Terminal):* `xattr -dr com.apple.quarantine /Applications/PropBench.app`

### Windows (x64 or ARM64)
1. Run `PropBench_*_x64-setup.exe`. It installs for your user only and needs no administrator rights. If **Windows
   protected your PC** (SmartScreen) appears, click **More info**, then **Run anyway**.
2. Finish the installer. Some antivirus programs may also ask for confirmation for an unsigned app.

### Linux
- **AppImage (no administrator rights):** `chmod +x PropBench-*.AppImage` then run it (or right-click › Properties ›
  *Allow executing as program*).
- **.deb (Ubuntu/Debian; needs administrator rights):** `sudo apt install ./propbench_*.deb`

### Verify the download (recommended)
- macOS/Linux: `shasum -a 256 <file>` · Windows (PowerShell): `Get-FileHash <file> -Algorithm SHA256`
- Compare with `SHA256SUMS.txt` on the release page.

Signed installers and package-manager installs (winget, Homebrew, Flathub) are planned and will remove these steps.
Extra components (experimental data, engines, add-ons) download from inside the app when a task needs them
(**Tools › Components**).

## Your first project: viscosity of CF₃I
1. **Create the project.** File › New project → *Fit a model to my measurements*. The wizard installs missing components.
2. **Import the data.** Data › Import → `Viscosity_CF3I_TUHIN_20240327.xlsx`. Map columns to quantities and units
   (p in MPa, T in K, η in μPa·s, expanded uncertainty in %). Record the source DOI.
3. **Check the data.** Units are converted to SI, phases compared with the equation of state, duplicates detected.
   The check reports the 333–338 K overlap with the 1999 data and suggests a consistency study.
4. **Set up the study.** Choose models, validation (leave one state out), physics checks; **lock the selection rule
   before fitting**; Run all.
5. **Read the results.** ECS ψ(δ) + k is selected: 0.54 % (liquid) and 0.49 % (vapour) on unseen states, no
   physics violations. Rejected models are listed with the reason.
6. **Script it.** Everything is available from Python in the project environment:

```python
import propbench as pb
proj  = pb.open("CF3I viscosity.pbp")
model = pb.models.ECS(reference="R134a", shape="linear", dilute_gas_factor=True)
study = pb.validate(model, proj.datasets["Tuhin 2024"], scheme="loso", seed=2026)
print(study.summary())
```
