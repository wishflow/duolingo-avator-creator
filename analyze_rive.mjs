import fs from "fs";
import path from "path";
import { createCanvas } from "canvas";
import riveCanvasInit from "@rive-app/canvas";

const ASSETS_DIR = path.join(process.cwd(), "assets");
const RIVE_PATH = path.join(ASSETS_DIR, "avatar_builder_25_sept2025.riv");

async function main() {
  console.log("[*] Initializing Rive runtime...");
  // For Node.js, we need to provide a locateFile function
  const riveRuntime = await riveCanvasInit({
    locateFile: (file) => {
      if (file.endsWith(".wasm")) {
        return path.join(
          process.cwd(),
          "node_modules/@rive-app/canvas/rive.wasm"
        );
      }
      return file;
    },
  });

  console.log("[*] Reading Rive file...");
  const buffer = fs.readFileSync(RIVE_PATH);
  const bytes = new Uint8Array(buffer);

  console.log("[*] Loading Rive file...");
  const file = await riveRuntime.load(bytes);
  console.log("[OK] File loaded successfully!\n");

  // List all artboards
  const artboardCount = file.artboardCount();
  console.log(`=== ARTBOARDS (${artboardCount}) ===`);
  for (let i = 0; i < artboardCount; i++) {
    const ab = file.artboardByIndex(i);
    const bounds = ab.bounds;
    console.log(
      `  [${i}] "${ab.name}" bounds: (${bounds.minX}, ${bounds.minY}) - (${bounds.maxX}, ${bounds.maxY})`
    );
  }

  // List all animations
  const animCount = file.animationCount();
  console.log(`\n=== ANIMATIONS (${animCount}) ===`);
  for (let i = 0; i < Math.min(animCount, 150); i++) {
    const anim = file.animationByIndex(i);
    console.log(`  [${i}] "${anim.name}"`);
  }
  if (animCount > 150) {
    console.log(`  ... and ${animCount - 150} more animations`);
  }

  // List all state machines
  const smCount = file.stateMachineCount();
  console.log(`\n=== STATE MACHINES (${smCount}) ===`);
  for (let i = 0; i < smCount; i++) {
    const sm = file.stateMachineByIndex(i);
    console.log(`  [${i}] "${sm.name}" with ${sm.inputCount()} inputs:`);
    for (let j = 0; j < sm.inputCount(); j++) {
      const input = sm.inputByIndex(j);
      console.log(
        `    [${j}] "${input.name}" type=${input.type} (${input.type === 56 ? "Number" : input.type === 59 ? "Boolean" : input.type === 58 ? "Trigger" : "Unknown"})`
      );
    }
  }

  // Try to render each artboard as PNG
  console.log(`\n=== RENDERING ARTBOARDS ===`);
  const outputDir = path.join(ASSETS_DIR, "artboards");
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  for (let i = 0; i < artboardCount; i++) {
    const ab = file.artboardByIndex(i);
    const canvas = createCanvas(500, 500);
    const renderer = riveRuntime.makeRenderer(canvas);

    renderer.clear();
    ab.advance(0);

    // If there's a state machine, use the first one
    if (smCount > 0 && file.stateMachineCount() > 0) {
      try {
        const sm = file.stateMachineByIndex(0);
        const smi = new riveRuntime.StateMachineInstance(ab, sm);

        // Set default state values from the config
        // Based on Duolingo config: Body=1, Expression=1, MainHair=58, etc.
        const defaultState = {
          BackgroundColor: 1,
          Body: 1,
          ClothingColor: 1,
          Expression: 5,
          EyeColor: 1,
          FacialHair: 0,
          FacialHairColor: 1,
          Glasses: 0,
          GlassesColor: 1,
          Headwear: 0,
          HeadwearColor: 1,
          MainHair: 58,
          MainHairColor: 1,
          "Nose Piercing": 0,
          Piercings: 0,
          SkinTone: 15,
          Wrinkles: 0,
        };

        // Apply state through inputs
        for (let j = 0; j < smi.inputCount(); j++) {
          const inputDef = sm.inputByIndex(j);
          const inputInst = smi.inputByIndex(j);
          const name = inputDef.name;
          if (defaultState[name] !== undefined) {
            if (inputDef.type === 59) {
              inputInst.value = defaultState[name] !== 0;
            } else if (inputDef.type === 56) {
              inputInst.value = defaultState[name];
            }
          }
        }
        smi.advance(0);
      } catch (e) {
        console.log(`  [${i}] State machine error: ${e.message}`);
      }
    }

    ab.draw(renderer);

    const outPath = path.join(outputDir, `artboard_${i}_${ab.name.replace(/[/\\?%*:|"<>]/g, "_")}.png`);
    const pngBuffer = canvas.toBuffer("image/png");
    fs.writeFileSync(outPath, pngBuffer);
    console.log(`  [${i}] Saved: ${outPath} (${(pngBuffer.length / 1024).toFixed(1)} KB)`);
  }

  // Now try to extract individual feature variations
  // For each state machine input, iterate through possible values
  console.log(`\n=== EXTRACTING FEATURE VARIATIONS ===`);

  // Let's try to find the artboard that contains facial features
  // Usually there's one main artboard with the character
  const mainArtboard = file.artboardByIndex(0);
  const mainSM = file.stateMachineByIndex(0);
  const inputNames = [];
  for (let j = 0; j < mainSM.inputCount(); j++) {
    inputNames.push(mainSM.inputByIndex(j).name);
  }
  console.log(`State machine inputs: ${inputNames.join(", ")}`);

  // Based on Duolingo config, key inputs for facial features:
  // Expression (values 1-57), MainHair (values 1-73), FacialHair (0-6),
  // Glasses (0-6), Headwear (0-11), Body (1-6), etc.

  const featuresDir = path.join(ASSETS_DIR, "features");
  if (!fs.existsSync(featuresDir)) {
    fs.mkdirSync(featuresDir, { recursive: true });
  }

  // Render a few expression variations
  const expressionInputIdx = inputNames.indexOf("Expression");
  if (expressionInputIdx >= 0) {
    console.log(`\nExtracting Expression variations...`);
    for (let val = 1; val <= 10; val++) {
      const canvas = createCanvas(500, 500);
      const renderer = riveRuntime.makeRenderer(canvas);
      renderer.clear();

      const smi = new riveRuntime.StateMachineInstance(mainArtboard, mainSM);

      // Set all inputs to defaults, only change Expression
      const defaults = {
        BackgroundColor: 22,
        Body: 4,
        ClothingColor: 2,
        Expression: val,
        EyeColor: 1,
        FacialHair: 0,
        FacialHairColor: 1,
        Glasses: 0,
        GlassesColor: 1,
        Headwear: 0,
        HeadwearColor: 1,
        MainHair: 58,
        MainHairColor: 2,
        "Nose Piercing": 0,
        Piercings: 0,
        SkinTone: 8,
        Wrinkles: 0,
      };

      for (let j = 0; j < smi.inputCount(); j++) {
        const inputDef = mainSM.inputByIndex(j);
        const inputInst = smi.inputByIndex(j);
        const name = inputDef.name;
        if (defaults[name] !== undefined) {
          if (inputDef.type === 59) {
            inputInst.value = defaults[name] !== 0;
          } else if (inputDef.type === 56) {
            inputInst.value = defaults[name];
          }
        }
      }

      smi.advance(0);
      mainArtboard.advance(0);
      mainArtboard.draw(renderer);

      const outPath = path.join(featuresDir, `expression_${val}.png`);
      fs.writeFileSync(outPath, canvas.toBuffer("image/png"));
      console.log(`  Saved expression_${val}.png`);
    }
  }

  // Save summary JSON
  const summary = {
    artboards: [],
    stateMachines: [],
    animations: [],
  };

  for (let i = 0; i < file.artboardCount(); i++) {
    const ab = file.artboardByIndex(i);
    summary.artboards.push({ index: i, name: ab.name });
  }

  // Get just the input names for the summary
  for (let i = 0; i < file.stateMachineCount(); i++) {
    const sm = file.stateMachineByIndex(i);
    const inputs = [];
    for (let j = 0; j < sm.inputCount(); j++) {
      const inp = sm.inputByIndex(j);
      inputs.push({ name: inp.name, type: inp.type });
    }
    summary.stateMachines.push({ index: i, name: sm.name, inputCount: sm.inputCount(), inputs });
  }

  fs.writeFileSync(
    path.join(ASSETS_DIR, "rive_structure.json"),
    JSON.stringify(summary, null, 2)
  );
  console.log(`\n[OK] Structure saved to rive_structure.json`);

  file.delete();
  riveRuntime.cleanup();
}

main().catch((err) => {
  console.error("FATAL:", err.message);
  console.error(err.stack);
  process.exit(1);
});
