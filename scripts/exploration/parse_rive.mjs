import fs from "fs";
import path from "path";
import rivePkg from "@rive-app/canvas";
const Rive = rivePkg.Rive || rivePkg.default?.Rive || rivePkg;

const ASSETS_DIR = path.join(process.cwd(), "assets");
const rivePath = path.join(ASSETS_DIR, "avatar_builder_25_sept2025.riv");

async function main() {
  console.log("[*] Loading Rive file...");
  const buffer = fs.readFileSync(rivePath);
  const bytes = new Uint8Array(buffer);

  const riveFile = await Rive.load(bytes);
  console.log(`[*] Loaded successfully`);

  // List artboards
  const artboardCount = riveFile.artboardCount;
  console.log(`\n=== Artboards (${artboardCount}) ===`);
  for (let i = 0; i < artboardCount; i++) {
    const ab = riveFile.artboardByIndex(i);
    console.log(`  [${i}] "${ab.name}"`);
  }

  // List animations
  const animCount = riveFile.animationCount;
  console.log(`\n=== Animations (${animCount}) ===`);
  for (let i = 0; i < Math.min(animCount, 100); i++) {
    const anim = riveFile.animationByIndex(i);
    console.log(`  [${i}] "${anim.name}"`);
  }
  if (animCount > 100) {
    console.log(`  ... and ${animCount - 100} more`);
  }

  // List state machines
  const smCount = riveFile.stateMachineCount;
  console.log(`\n=== State Machines (${smCount}) ===`);
  for (let i = 0; i < smCount; i++) {
    const sm = riveFile.stateMachineByIndex(i);
    console.log(`  [${i}] "${sm.name}" (${sm.inputCount} inputs)`);
    for (let j = 0; j < sm.inputCount; j++) {
      const input = sm.inputByIndex(j);
      console.log(`    input[${j}]: "${input.name}" type=${input.type}`);
    }
  }

  // Try to find an artboard and enumerate its objects
  if (artboardCount > 0) {
    const ab = riveFile.artboardByIndex(0);
    console.log(`\n=== First Artboard "${ab.name}" details ===`);

    // Get the first state machine
    if (smCount > 0) {
      const sm = riveFile.stateMachineByIndex(0);
      console.log(`\n  State Machine: "${sm.name}"`);
      for (let j = 0; j < sm.inputCount; j++) {
        const input = sm.inputByIndex(j);
        console.log(`    "${input.name}": type=${input.type}`);
      }
    }
  }

  riveFile.delete();
}

main().catch((err) => {
  console.error("Error:", err.message);
  console.error(err.stack);
  process.exit(1);
});
