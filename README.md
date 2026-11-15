# Space City Racing

A 3D racing game set in a space city.

## Tools

| Job | Tool | Status |
|---|---|---|
| Game engine | **Unreal Engine 5** (Blueprints first, C++ later if needed) | ⏳ You install it (step 1) |
| 3D modeling | **Blender 5.3** | ✅ Installed at `E:\Blender` |
| Launcher | **Epic Games Launcher** | ✅ Already had it |
| Version control | **Git + Git LFS** | ✅ Repo set up in this folder |

## Folder layout

```
space city racing/
├── Art/
│   ├── Blender/      ← your .blend source files
│   └── Exports/      ← .fbx files exported for Unreal
├── SpaceCityRacing/  ← the Unreal project (created in step 2)
├── .gitignore        ← keeps Unreal's huge cache folders out of Git
└── .gitattributes    ← sends big files (models, textures, levels) through Git LFS
```

---

## Step 1: Install Unreal Engine on the E: drive

> ⚠️ **Your C: drive only has about 5 GB free.** Unreal needs 60 GB or more, so install it on **E:**.

1. Open the **Epic Games Launcher** and sign in.
2. Go to **Unreal Engine** (left sidebar), then the **Library** tab.
3. Next to **Engine Versions**, click **+** and pick the newest **5.x** version.
4. Click **Install**. When it asks for a location, choose **`E:\Epic Games`**.
5. Before confirming, click **Options** and **untick** what you don't need yet. This saves a lot of space:
   - **Editor symbols for debugging** (this one is huge)
   - **Android**, **iOS**, **Linux** target platforms (you can add them later)
6. Wait for the download to finish. It's big.

## Step 2: Create the project from the Vehicle template

The Vehicle template already gives you a drivable car on a test track, so it covers the "car on a flat track" first test.

1. In the Library, click **Launch** on the engine version you installed.
2. In the Project Browser, choose **Games**, then **Vehicle**.
3. Settings:
   - **Blueprint** (not C++)
   - **Starter Content**: on
   - **Location**: `E:\space city racing`
   - **Name**: `SpaceCityRacing`
4. Click **Create**.
5. Press **Play** (or Alt+P) and drive with **W A S D**. If the car drives, the setup is complete.

## Step 3: Keep Unreal's cache off the C: drive

Unreal stores a large shader cache in your user folder on C: by default. The `UE-LocalDataCachePath` setting in your Windows user environment points it at `E:\UnrealCache` instead. Restart the launcher or editor after it's set so the change takes effect.

To check or undo it later, search Windows for **"Edit environment variables for your account"**.

---

## Blender → Unreal workflow

1. Model in **real-world meters** (Blender's default). A car is about 4.5 m long.
2. Select the object and press **Ctrl+A, then All Transforms** to apply the scale.
3. Save the source file to `Art/Blender/`.
4. Go to **File → Export → FBX** and save to `Art/Exports/`. In the export options, set **Apply Scalings: FBX Units Scale**.
5. In Unreal, drag the `.fbx` into the Content Browser.

## Roadmap (for later)

- [ ] Drive the template car around (step 2)
- [ ] Model a first space car in Blender and swap it in
- [ ] Build a test track through a city block
- [ ] Lap timer and checkpoints
- [ ] Space city look: neon, skyscrapers, floating platforms
