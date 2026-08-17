"""Generate the version-diff port for the fork's Live2D reader as a reviewable patch.

This session cannot write outside the pipeline repo, so the port is produced here
instead of applied in place: every edit is a surgical string replacement against the
fork's current files, each one asserted to match exactly once, and the result is
emitted both as staged files and as a unified diff.

    python port/build_live2d_port.py            # writes port/live2d-version-diff.patch
    cd ../sekai-viewer-diff && git apply ../sekai-story-diff/port/live2d-version-diff.patch

Today only the *text* reader shows what a line used to say. The Live2D player draws
its dialogue in pixi, so the same information has to go through the Dialog layer. It
gets its own stacked text slot above the current line — deliberately not reusing the
LLM translation slot, so a translated JP story can still show both.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

FORK = Path("../sekai-viewer-diff")
STAGE = Path("port/live2d-version-diff")
PATCH = Path("port/live2d-version-diff.patch")

# (path, [(anchor, replacement), ...]) — each anchor must appear exactly once
EDITS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "src/utils/Live2DPlayer/types.d.ts",
        [
            (
                """export interface ILive2DControllerData {
  scenarioData: IScenarioData;
  scenarioResource: ILive2DScenarioResource;
  modelData: ILive2DModelDataCollection[];
}""",
                """export interface ILive2DControllerData {
  scenarioData: IScenarioData;
  scenarioResource: ILive2DScenarioResource;
  modelData: ILive2DModelDataCollection[];
  /**
   * What these lines said in an earlier asset version, when a snapshot has been
   * published for the scenario. Absent for everything else, which reads normally.
   */
  versionDiff?: VersionDiffSnapshot | null;
}""",
            ),
        ],
    ),
    (
        "src/utils/Live2DPlayer/Live2DController.ts",
        [
            (
                """import single_action from "./action";""",
                """import single_action from "./action";
import {
  indexChangedLines,
  type VersionDiffLine,
  type VersionDiffSnapshot,
} from "../versionDiff";""",
            ),
            (
                """  scenarioData: IScenarioData;
  scenarioResource: ILive2DScenarioResource;
  modelData: ILive2DModelDataCollection[];
  model_queue: string[][];""",
                """  scenarioData: IScenarioData;
  scenarioResource: ILive2DScenarioResource;
  modelData: ILive2DModelDataCollection[];
  versionDiff: VersionDiffSnapshot | null;
  /** TalkData index → the line as it shipped in the older asset version */
  changedLines: Map<number, VersionDiffLine>;
  model_queue: string[][];""",
            ),
            (
                """    this.scenarioData = data.scenarioData;
    this.scenarioResource = data.scenarioResource;
    this.modelData = data.modelData;""",
                """    this.scenarioData = data.scenarioData;
    this.scenarioResource = data.scenarioResource;
    this.modelData = data.modelData;
    this.versionDiff = data.versionDiff ?? null;
    this.changedLines = indexChangedLines(this.versionDiff);""",
            ),
        ],
    ),
    (
        "src/utils/Live2DPlayer/layer/Dialog.ts",
        [
            # --- draw(): accept and build the previous-version slot
            (
                """  /**
   * Draw dialog with original text and optional translated text
   * @param cn Character name
   * @param text Original text
   * @param translatedText Optional translated text
   */
  draw(cn: string, text: string, translatedText?: string | null) {""",
                """  /**
   * Draw dialog with original text, optional translation and optional previous text
   * @param cn Character name
   * @param text Original text
   * @param translatedText Optional translated text
   * @param previousText Optional text this line had in an earlier asset version
   */
  draw(
    cn: string,
    text: string,
    translatedText?: string | null,
    previousText?: string | null
  ) {""",
            ),
            (
                """    // Create translated text element if translation is provided
    let translated_text_c: Text | undefined;
    if (translatedText) {
      translated_text_c = new Text(translatedText);
      text_container.addChild(translated_text_c);
    }""",
                """    // Create translated text element if translation is provided
    let translated_text_c: Text | undefined;
    if (translatedText) {
      translated_text_c = new Text(translatedText);
      text_container.addChild(translated_text_c);
    }

    // Create previous-version element, stacked above both
    let previous_text_c: Text | undefined;
    if (previousText) {
      previous_text_c = new Text(previousText);
      text_container.addChild(previous_text_c);
    }""",
            ),
            (
                """      cn_c,
      text_container,
      text_c,
      translated_text_c,
    };""",
                """      cn_c,
      previous_text_c,
      text_container,
      text_c,
      translated_text_c,
    };""",
            ),
            (
                """    cn_c?: Text;
    text_container?: Container;
    text_c?: Text;
    translated_text_c?: Text;
  };""",
                """    cn_c?: Text;
    text_container?: Container;
    text_c?: Text;
    translated_text_c?: Text;
    previous_text_c?: Text;
  };""",
            ),
            # --- draw_new_text(): keep the previous slot alive across the typewriter
            (
                """  draw_new_text(text: string, translatedText?: string | null) {
    if (this.init) {
      const new_text = new Text(text);
      this.structure.text_container?.addChild(new_text);
      this.structure.text_c?.destroy();
      this.structure.text_c = new_text;

      this.structure.translated_text_c?.destroy();
      // Update translated text if provided
      if (translatedText) {
        const new_translated_text = new Text(translatedText);
        this.structure.text_container?.addChild(new_translated_text);
        this.structure.translated_text_c = new_translated_text;
      } else {
        this.structure.translated_text_c = undefined;
      }

      this.set_style_dialog_text();
    }
  }""",
                """  draw_new_text(
    text: string,
    translatedText?: string | null,
    previousText?: string | null
  ) {
    if (this.init) {
      const new_text = new Text(text);
      this.structure.text_container?.addChild(new_text);
      this.structure.text_c?.destroy();
      this.structure.text_c = new_text;

      this.structure.translated_text_c?.destroy();
      // Update translated text if provided
      if (translatedText) {
        const new_translated_text = new Text(translatedText);
        this.structure.text_container?.addChild(new_translated_text);
        this.structure.translated_text_c = new_translated_text;
      } else {
        this.structure.translated_text_c = undefined;
      }

      this.structure.previous_text_c?.destroy();
      // The previous line does not animate — it is context for the line being typed
      if (previousText) {
        const new_previous_text = new Text(previousText);
        this.structure.text_container?.addChild(new_previous_text);
        this.structure.previous_text_c = new_previous_text;
      } else {
        this.structure.previous_text_c = undefined;
      }

      this.set_style_dialog_text();
    }
  }""",
            ),
            # --- layout: stack previous → translated → current
            (
                """    // Calculate starting position for text
    let originalTextYPosition = this.em(35);

    // Count lines directly from text strings
    let translatedLineCount = 0;
    let originalLineCount = 0;""",
                """    // Calculate starting position for text
    let originalTextYPosition = this.em(35);

    // Count lines directly from text strings
    let translatedLineCount = 0;
    let originalLineCount = 0;
    let previousLineCount = 0;

    // Style the previous-version line, above everything else. Dimmer and smaller
    // than the current line so it reads as context rather than as the dialogue.
    if (this.structure.previous_text_c) {
      const previous_text = this.structure.previous_text_c;
      previousLineCount = previous_text.text.split("\\n").length;
      previous_text.x = margin_left + this.em(3);
      previous_text.y = originalTextYPosition;
      previous_text.alpha = 0.55;
      previous_text.style = new TextStyle({
        fill: ["#ffd7d7"],
        fontSize: this.em(9),
        lineHeight: this.em(11),
        breakWords: true,
        wordWrap: true,
        wordWrapWidth: this.stage_size[0] - margin_left * 2,
        stroke: "#4a4968aa",
        strokeThickness: this.em(2),
        lineJoin: "round",
      });
      originalTextYPosition += previous_text.height + this.em(2);
    }""",
            ),
            (
                """    // Style translated text (displayed above original text)
    if (this.structure.translated_text_c) {
      const translated_text = this.structure.translated_text_c;
      translated_text.x = margin_left + this.em(3);
      translated_text.y = this.em(35);""",
                """    // Style translated text (displayed above original text)
    if (this.structure.translated_text_c) {
      const translated_text = this.structure.translated_text_c;
      translated_text.x = margin_left + this.em(3);
      translated_text.y = originalTextYPosition;""",
            ),
            (
                """      // Dynamically calculate position for original text based on translated text height
      originalTextYPosition = this.em(35) + translated_text.height;
    }""",
                """      // Dynamically calculate position for original text based on translated text height
      originalTextYPosition += translated_text.height;
    }""",
            ),
            (
                """    const text = this.structure.text_c!;
    text.x = margin_left + this.em(3);
    text.y = originalTextYPosition;
    text.style = new TextStyle({
      fill: ["#ffffff"],
      fontSize: this.structure.translated_text_c ? this.em(13) : this.em(16),
      lineHeight: this.structure.translated_text_c ? this.em(16) : this.em(22),""",
                """    const text = this.structure.text_c!;
    const stacked =
      !!this.structure.translated_text_c || !!this.structure.previous_text_c;
    text.x = margin_left + this.em(3);
    text.y = originalTextYPosition;
    text.style = new TextStyle({
      fill: ["#ffffff"],
      fontSize: stacked ? this.em(13) : this.em(16),
      lineHeight: stacked ? this.em(16) : this.em(22),""",
            ),
            (
                """      stroke: "#4a4968aa",
      strokeThickness: this.structure.translated_text_c
        ? this.em(3)
        : this.em(4),
      lineJoin: "round",
    });
    // If total lines >= 6, make text smaller
    if (translatedLineCount + originalLineCount >= 6) {""",
                """      stroke: "#4a4968aa",
      strokeThickness: stacked ? this.em(3) : this.em(4),
      lineJoin: "round",
    });
    // If total lines >= 6, make text smaller
    if (translatedLineCount + originalLineCount + previousLineCount >= 6) {""",
            ),
            # --- animate(): thread it through the typewriter
            (
                """  async animate(cn: string, text: string, translatedText?: string | null) {
    this.draw(cn, "");
    for (let i = 1; i <= text.length; i++) {
      // if aborted, jump to full text
      if (this.animation_controller.abort_controller.signal.aborted) {
        i = text.length;
      }
      // new text
      this.draw_new_text(text.slice(0, i), translatedText);
      await this.animation_controller.delay(50);
    }
  }""",
                """  async animate(
    cn: string,
    text: string,
    translatedText?: string | null,
    previousText?: string | null
  ) {
    this.draw(cn, "", null, previousText);
    for (let i = 1; i <= text.length; i++) {
      // if aborted, jump to full text
      if (this.animation_controller.abort_controller.signal.aborted) {
        i = text.length;
      }
      // new text
      this.draw_new_text(text.slice(0, i), translatedText, previousText);
      await this.animation_controller.delay(50);
    }
  }""",
            ),
        ],
    ),
    (
        "src/utils/Live2DPlayer/action/talk.ts",
        [
            (
                """  //clear
  await controller.layers.telop.hide(200);""",
                """  // What this line said in an earlier asset version, when one is published.
  // Snapshots store the line unwrapped while Body carries the on-screen line
  // breaks, so compare on collapsed whitespace — otherwise a name-plate-only
  // change would show a "before" line identical to the one below it.
  const diff = controller.changedLines.get(action.ReferenceIndex);
  const collapse = (s: string) => s.replace(/\\s+/g, " ").trim();
  const previousText =
    diff && collapse(diff.old) !== collapse(originalText)
      ? `${controller.versionDiff?.oldAssetVersion ?? "before"}:  ${diff.old}`
      : null;

  //clear
  await controller.layers.telop.hide(200);""",
            ),
            (
                """    dialog = controller.layers.dialog.animate(
      action_detail.WindowDisplayName,
      displayText,
      translatedText
    );
  } else {
    controller.layers.dialog.draw(
      action_detail.WindowDisplayName,
      displayText,
      translatedText
    );
  }""",
                """    dialog = controller.layers.dialog.animate(
      action_detail.WindowDisplayName,
      displayText,
      translatedText,
      previousText
    );
  } else {
    controller.layers.dialog.draw(
      action_detail.WindowDisplayName,
      displayText,
      translatedText,
      previousText
    );
  }""",
            ),
        ],
    ),
    (
        "src/pages/storyreader-live2d/StoryReaderLive2DContent.tsx",
        [
            (
                """      controllerData.current = ctData;
      setLoadStatus(LoadStatus.Loaded);""",
                """      // step 6 - version diff, if a snapshot has been published for this scenario.
      // Failing to find one is the normal case and must not block the reader.
      try {
        const scenarioId = storyId.split("/").pop();
        if (scenarioId) {
          ctData.versionDiff = await getVersionDiff(scenarioId, region);
        }
      } catch (err) {
        console.warn("version diff unavailable:", err);
      }
      controllerData.current = ctData;
      setLoadStatus(LoadStatus.Loaded);""",
            ),
        ],
    ),
]

# import lines that need adding, keyed by file
IMPORTS = {
    "src/utils/Live2DPlayer/types.d.ts": (
        'import type { VersionDiffSnapshot } from "../versionDiff";\n',
    ),
    "src/pages/storyreader-live2d/StoryReaderLive2DContent.tsx": (
        'import { getVersionDiff } from "../../utils/versionDiff";\n',
    ),
}


def main() -> None:
    if not (FORK / "src/utils/versionDiff.ts").exists():
        raise SystemExit(f"{FORK} is not the fork with the version-diff branch")

    diffs: list[str] = []
    for rel, edits in EDITS:
        src = FORK / rel
        original = src.read_text()
        text = original
        for anchor, replacement in edits:
            found = text.count(anchor)
            if found != 1:
                raise SystemExit(
                    f"{rel}: anchor matched {found} times, expected 1:\n"
                    f"---\n{anchor[:200]}\n---"
                )
            text = text.replace(anchor, replacement)
        for line in IMPORTS.get(rel, ()):
            if line not in text:
                text = line + text
        out = STAGE / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        diffs.extend(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                text.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
        print(f"  {rel}: {len(edits)} edits applied")

    PATCH.write_text("".join(diffs))
    added = sum(1 for line in diffs if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diffs if line.startswith("-") and not line.startswith("---"))
    print(f"\nwrote {PATCH} (+{added} / -{removed} lines across {len(EDITS)} files)")
    print(f"staged files under {STAGE}/")


if __name__ == "__main__":
    sys.exit(main())
