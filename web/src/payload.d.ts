/**
 * The shape of `data.json`, as emitted by `scripts/build_web_gallery.py`.
 *
 * Hand-written, and kept honest by a drift check in `test/check-range.mjs` that walks the
 * real payload against these declarations. The alternative — generating this from the
 * builder — would mean refactoring four inline dict literals in working pipeline code for
 * a guarantee the test gives more cheaply.
 *
 * Do not try to infer this from `data.json`. Two fields in the current build make that
 * unsound: `dropped` and `pending` are both `[]`, which infers as `never[]`; and `cover`
 * is `""` on all 1,107 frames while the code branches on `"white"`, so inference can only
 * ever see one member of a three-member union.
 */

/**
 * A string that already contains markup — the payload's diff runs are real `<b>` tags and
 * Python's `html.escape()` has turned `& < > " '` into entities.
 *
 * Branded because the compiler cannot otherwise tell it from ordinary text, and that
 * confusion is not hypothetical: `strip()` was fed HTML it only half-decoded, which left
 * `&#x27;` in the search haystack and made 57% of the corpus unmatchable by any query
 * containing an apostrophe. Nothing reported it, because both sides were `string`.
 */
export type Html = string & { readonly __html: unique symbol };

/**
 * A 1-based line number in our own numbering — the `#34` on a frame, an index into the
 * scenario's `TalkData` plus one.
 */
export type LineNo = number & { readonly __line: unique symbol };

/**
 * A 1-based line number in the outbound reader's numbering, which counts *steps* rather
 * than talks: a full-screen telop is a step you click through, so it runs ahead of
 * `LineNo` by however many telops preceded it.
 *
 * Distinct from `LineNo` because substituting one for the other is a silent 94%-wrong
 * link that lands on plausible adjacent dialogue rather than visibly breaking.
 */
export type ReaderNo = number & { readonly __reader: unique symbol };

/** How far the text actually moved, per transition. */
export type Magnitude = "retranslation" | "revised" | "punctuation";

/** A full-screen fill replacing the background, or `""` when the scene has artwork. */
export type Cover = "" | "white" | "black";

/** One rendered character on the stage, positioned as a percentage of it. */
export interface Sprite {
  file: string;
  /** height, as a percentage of the stage */
  h: number;
  left: number;
  top: number;
  w: number;
}

/** A character in one frame: which sprite, where, and how it stacks. */
export interface Layer {
  depth: number;
  /** horizontal nudge from the sprite's own stored position, in stage percent */
  dx: number;
  /** key into `Payload.sprites` */
  key: string;
  speaking: boolean;
}

/** One changed line, rendered before and after. */
export interface Frame {
  /** background asset id; meaningless when `cover` is set */
  bg: string;
  cover: Cover;
  flashback: boolean;
  /** the Japanese source line — plain text, never markup */
  jp: string;
  layers: Layer[];
  new: Html;
  old: Html;
  readerLine: ReaderNo;
  speaker: string;
  /** the speaker's previous name; differs from `speaker` on a rename */
  speakerOld: string;
  talkIndex: LineNo;
}

export interface Episode {
  frames: Frame[];
  no: number;
  /** the game's own id for this scenario, e.g. `event_01_01` */
  scenarioId: string;
  /** URL segment, e.g. `ep03-less-stars-more-bass` */
  slug: string;
  title: string;
}

/** One release at which this story's text changed. */
export interface Transition {
  /** share of the story's lines that moved, 0–1 */
  breadth: number;
  changed: number;
  /** how far the changed lines moved, 0–1 */
  depth: number;
  episodes: Episode[];
  label: Magnitude;
  newReleasedAt: string;
  newVersion: string;
  oldReleasedAt: string;
  oldVersion: string;
}

/**
 * An event story, or a unit arc carried as a pseudo-event in id range 9000+ so that
 * search, range filtering and the drawer need no second code path.
 */
export interface EventEntry {
  /** path under the asset base; `""` for arcs, which have no chapter art */
  banner: string;
  /** the game's asset bundle name, for the outbound reader link */
  bundleName: string;
  changed: number;
  colour: string;
  id: number;
  kind: "event" | "arc";
  /** event title art; `""` for arcs */
  logo: string;
  name: string;
  nameJp: string;
  /** short label for the drawer, where the unit is already named; `""` for events */
  shortName: string;
  slug: string;
  transitions: Transition[];
  unit: string;
  unitLogo: string;
}

/** An event the mirror shows as re-uploaded, awaiting a diff. Rendered as a dead card. */
export interface PendingEvent {
  banner: string;
  colour: string;
  id: number;
  name: string;
  nameJp: string;
  unit: string;
  unitLogo: string;
}

/** A changed line that could not be rendered, kept so the omission is visible. */
export interface Dropped {
  episode_no: number;
  event_id: number;
  reason: string;
  speaker: string;
  talk_index: number;
}

export interface Version {
  date: string;
  version: string;
}

export interface Comparison {
  new_asset_version: string;
  old_asset_version: string;
  region: string;
}

export interface Payload {
  comparison: Comparison;
  dropped: Dropped[];
  events: EventEntry[];
  pending: PendingEvent[];
  /** every release the CDN still serves, oldest first */
  versions: Version[];
  sprites: Record<string, Sprite>;
}
