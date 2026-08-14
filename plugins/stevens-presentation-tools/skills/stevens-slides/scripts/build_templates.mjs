import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const WIDTH = 1280;
const HEIGHT = 720;
const TITLE_PX = 40 * 4 / 3;
const COVER_PX = 54 * 4 / 3;
const SUBHEAD_PX = 20 * 4 / 3;
const BODY_PX = 18 * 4 / 3;
const TITLE_FACE = "Saira Condensed";
const BODY_FACE = "IBM Plex Sans";

const THEMES = {
  white: {
    name: "White",
    surface: "#FFFFFF",
    onSurface: "#363D45",
    secondary: "#7F7F7F",
    subtle: "#E4E5E6",
    brandPlane: "#A32638",
    logo: "positive",
    series: ["#A32638", "#004380", "#EBC73B"],
    nodeFill: "#E7F2FB",
    nodeText: "#363D45",
  },
  dark: {
    name: "Dark",
    surface: "#363D45",
    onSurface: "#FFFFFF",
    secondary: "#E4E5E6",
    subtle: "#7F7F7F",
    brandPlane: "#A32638",
    logo: "negative",
    series: ["#EBC73B", "#E7842E", "#4896CF"],
    nodeFill: "#004380",
    nodeText: "#FFFFFF",
  },
};

const ARCHETYPES = [
  {
    id: "text-cover",
    layoutName: "Stevens 01 — Text Cover",
    title: "Ideas that move technology forward",
    body: "Presentation title or concise thesis\nPresenter · Department · Date",
    kind: "textCover",
  },
  {
    id: "image-cover",
    layoutName: "Stevens 02 — Image Cover",
    title: "Research\nwith impact",
    body: "A visual opening for place, people, or purpose",
    kind: "imageCover",
  },
  {
    id: "roadmap",
    layoutName: "Stevens 03 — Roadmap",
    title: "Four moves turn a question into action",
    body: "Use this progression for an agenda, process, or learning path.",
    kind: "roadmap",
  },
  {
    id: "section-divider",
    layoutName: "Stevens 04 — Section Divider",
    title: "Frame the question\nbefore the answer",
    body: "Section 01 · Context and stakes",
    kind: "sectionDivider",
  },
  {
    id: "key-message",
    layoutName: "Stevens 05 — Key Message",
    title: "Give the central implication room to land",
    body: "One precise idea can carry an entire slide when the next decision depends on it.",
    kind: "keyMessage",
  },
  {
    id: "title-body",
    layoutName: "Stevens 06 — Title / Body",
    title: "A clear explanation earns attention",
    body: "Lead with the claim, support it with three short points, and make the consequence explicit.",
    kind: "titleBody",
  },
  {
    id: "two-column",
    layoutName: "Stevens 07 — Two Column",
    title: "Pair evidence with interpretation",
    body: "Evidence\nState what the audience can verify and why it is credible.",
    body2: "Meaning\nExplain how the evidence changes the decision or next step.",
    kind: "twoColumn",
  },
  {
    id: "three-point",
    layoutName: "Stevens 08 — Three Point",
    title: "Three ideas work when each has a distinct job",
    bodies: [
      "01 · Focus\nName the question.",
      "02 · Evidence\nShow what changed.",
      "03 · Action\nMake the next move clear.",
    ],
    kind: "threePoint",
  },
  {
    id: "text-figure-left",
    layoutName: "Stevens 09 — Text / Figure Left",
    title: "Let the evidence lead",
    body: "Use the right column to interpret the figure, call out the pattern, and state the implication.",
    kind: "textFigureLeft",
  },
  {
    id: "figure-text-right",
    layoutName: "Stevens 10 — Figure / Text Right",
    title: "Lead with the claim, then show the proof",
    body: "Keep the explanation concise so the figure remains the dominant evidence on the slide.",
    kind: "figureTextRight",
  },
  {
    id: "full-figure-caption",
    layoutName: "Stevens 11 — Full Figure + Caption",
    title: "One figure can carry the result",
    body: "Caption: identify the evidence, its source, and the takeaway the audience should retain.",
    kind: "fullFigure",
  },
  {
    id: "chart",
    layoutName: "Stevens 12 — Chart",
    title: "Direct labels clarify comparisons",
    body: "Illustrative data · replace values and source before presenting.",
    kind: "chart",
  },
  {
    id: "results-table",
    layoutName: "Stevens 13 — Results Table / Comparison",
    title: "Use a table when exact values matter",
    body: "Illustrative comparison · emphasize only the cells that change the conclusion.",
    kind: "table",
  },
  {
    id: "metrics",
    layoutName: "Stevens 14 — Metrics",
    title: "Headline metrics need definitions, not decoration",
    bodies: [
      "72%\nExample adoption",
      "2.4×\nExample speedup",
      "18 ms\nExample latency",
    ],
    kind: "metrics",
  },
  {
    id: "technical-canvas",
    layoutName: "Stevens 15 — Technical Canvas",
    title: "A clear diagram reveals the path",
    body: "Keep the topology small, label each stage, and use no more than four straight connections.",
    kind: "technical",
  },
  {
    id: "quote",
    layoutName: "Stevens 16 — Quote",
    title: "A quotation should sharpen the argument",
    body: "“Use a short, sourced quotation only when the speaker’s exact words add meaning.”\n— Source or speaker",
    kind: "quote",
  },
  {
    id: "closing",
    layoutName: "Stevens 17 — Closing / Q&A",
    title: "Questions?",
    body: "Resolve the opening, name the next action, or invite a focused discussion.\nname@stevens.edu",
    kind: "closing",
  },
];

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i];
    const value = argv[i + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`Invalid argument sequence near ${key ?? "end"}`);
    }
    args[key.slice(2)] = value;
  }
  for (const required of ["source", "asset-dir", "output-dir", "qa-dir"]) {
    if (!args[required]) throw new Error(`Missing --${required}`);
  }
  return args;
}

async function readBytes(filePath) {
  const bytes = await fs.readFile(filePath);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

function addShape(slide, name, geometry, position, fill, line = { style: "solid", fill: "none", width: 0 }) {
  return slide.shapes.add({ geometry, name, position, fill, line, shadow: "shadow-none" });
}

function addText(slide, name, text, position, style = {}) {
  const shape = addShape(slide, name, "textbox", position, "none");
  shape.text = text;
  shape.text.style = {
    typeface: style.typeface ?? BODY_FACE,
    fontSize: style.fontSize ?? BODY_PX,
    bold: style.bold ?? false,
    color: style.color ?? "#363D45",
    alignment: style.alignment ?? "left",
    verticalAlignment: style.verticalAlignment ?? "top",
    lineSpacing: style.lineSpacing ?? 1.15,
    autoFit: "none",
    wrap: "square",
    insets: style.insets ?? { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addLine(slide, name, left, top, width, color, weight = 2) {
  return addShape(
    slide,
    name,
    "line",
    { left, top, width, height: 0 },
    "none",
    { style: "solid", fill: color, width: weight },
  );
}

function addPageFooter(slide, theme, pageNumber, assets, options = {}) {
  const footerCenterY = 680;
  const footerTextTop = 664;
  const footerTextHeight = 32;
  const offset = options.offset ?? 0;
  const showStar = options.showStar ?? true;
  const showWordmark = options.showWordmark ?? true;
  if (showStar) {
    slide.images.add({
      blob: assets.star,
      contentType: "image/png",
      alt: "Official Stevens four-point star",
      fit: "contain",
      position: { left: 36 + offset, top: footerCenterY - 9, width: 18, height: 18 },
    });
  }
  if (showWordmark) {
    addText(slide, `footer-wordmark-${pageNumber}`, "STEVENS INSTITUTE OF TECHNOLOGY", { left: (showStar ? 66 : 36) + offset, top: footerTextTop, width: 250, height: footerTextHeight }, {
      fontSize: 13,
      bold: true,
      color: theme.onSurface,
      verticalAlignment: "middle",
      lineSpacing: 1,
    });
  }
  const ruleLeft = (showWordmark ? 326 : 36) + offset;
  addLine(slide, `footer-rule-${pageNumber}`, ruleLeft, footerCenterY, 1196 - ruleLeft, theme.secondary, 1);
  addText(slide, `page-number-${pageNumber}`, String(pageNumber), { left: 1205, top: footerTextTop, width: 40, height: footerTextHeight }, {
    fontSize: 16,
    color: theme.onSurface,
    alignment: "right",
    verticalAlignment: "middle",
    lineSpacing: 1,
  });
}

function addLogo(slide, theme, assets, position = { left: 1080, top: 48, width: 105, height: 128 }) {
  slide.images.add({
    blob: theme.logo === "positive" ? assets.logoPositive : assets.logoNegative,
    contentType: "image/png",
    alt: `Official Stevens ${theme.logo} identifier`,
    fit: "contain",
    position,
  });
}

function addBrandPlane(slide, theme, position, rotation = 0) {
  const plane = addShape(slide, "brand-plane", "parallelogram", { ...position, rotation }, theme.brandPlane);
  plane.sendToBack();
  return plane;
}

function addPlaceholder(layout, spec, theme) {
  const placeholder = layout.placeholders.add({
    type: spec.type,
    index: spec.index ?? 0,
    text: spec.text,
    geometry: "textbox",
    position: spec.position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  placeholder.text.style = {
    typeface: spec.typeface ?? BODY_FACE,
    fontSize: spec.fontSize ?? BODY_PX,
    bold: spec.bold ?? false,
    color: spec.color ?? theme.onSurface,
    alignment: spec.alignment ?? "left",
    verticalAlignment: spec.verticalAlignment ?? "top",
    lineSpacing: spec.lineSpacing ?? 1.15,
    autoFit: "none",
    wrap: "square",
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return placeholder;
}

function addSlidePlaceholder(slide, spec, theme) {
  const placeholder = slide.shapes.add({
    geometry: "textbox",
    name: `${spec.type}-placeholder-${spec.index ?? 0}`,
    position: spec.position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
    placeholderType: spec.type,
    placeholderIndex: spec.index ?? 0,
    shadow: "shadow-none",
  });
  placeholder.text = spec.text;
  placeholder.text.style = {
    typeface: spec.typeface ?? BODY_FACE,
    fontSize: spec.fontSize ?? BODY_PX,
    bold: spec.bold ?? false,
    color: spec.color ?? theme.onSurface,
    alignment: spec.alignment ?? "left",
    verticalAlignment: spec.verticalAlignment ?? "top",
    lineSpacing: spec.lineSpacing ?? 1.15,
    autoFit: "none",
    wrap: "square",
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return placeholder;
}

function layoutPlaceholders(archetype) {
  const standardTitle = {
    type: "title",
    index: 0,
    text: archetype.title,
    position: { left: 72, top: 50, width: 1040, height: 108 },
    typeface: TITLE_FACE,
    fontSize: TITLE_PX,
    bold: true,
    lineSpacing: 0.96,
  };
  switch (archetype.kind) {
    case "textCover":
      return [
        { ...standardTitle, position: { left: 72, top: 200, width: 790, height: 170 }, fontSize: COVER_PX },
        { type: "subtitle", index: 0, text: archetype.body, position: { left: 76, top: 390, width: 650, height: 86 }, fontSize: SUBHEAD_PX, lineSpacing: 1.18 },
      ];
    case "imageCover":
      return [
        { ...standardTitle, position: { left: 72, top: 205, width: 475, height: 170 }, fontSize: COVER_PX },
        { type: "subtitle", index: 0, text: archetype.body, position: { left: 76, top: 395, width: 455, height: 80 }, fontSize: SUBHEAD_PX },
      ];
    case "roadmap":
      return [standardTitle, { type: "body", index: 0, text: archetype.body, position: { left: 76, top: 142, width: 940, height: 54 }, fontSize: BODY_PX }];
    case "sectionDivider":
      return [
        { ...standardTitle, position: { left: 340, top: 246, width: 820, height: 140 }, fontSize: 64, lineSpacing: 0.96 },
        { type: "subtitle", index: 0, text: archetype.body, position: { left: 344, top: 410, width: 620, height: 50 }, fontSize: SUBHEAD_PX },
      ];
    case "keyMessage":
      return [
        standardTitle,
        { type: "body", index: 0, text: archetype.body, position: { left: 126, top: 246, width: 1030, height: 170 }, fontSize: 46, bold: true, lineSpacing: 1.06 },
      ];
    case "titleBody":
      return [
        standardTitle,
        { type: "body", index: 0, text: archetype.body, position: { left: 98, top: 190, width: 760, height: 150 }, fontSize: SUBHEAD_PX, lineSpacing: 1.28 },
      ];
    case "twoColumn":
      return [
        standardTitle,
        { type: "body", index: 0, text: archetype.body, position: { left: 76, top: 204, width: 500, height: 290 }, fontSize: SUBHEAD_PX, lineSpacing: 1.28 },
        { type: "content", index: 0, text: archetype.body2, position: { left: 704, top: 204, width: 500, height: 290 }, fontSize: SUBHEAD_PX, lineSpacing: 1.28 },
      ];
    case "threePoint":
      return [
        standardTitle,
        ...archetype.bodies.map((text, index) => ({
          type: "content",
          index,
          text,
          position: { left: 72 + index * 384, top: 236, width: 320, height: 210 },
          fontSize: SUBHEAD_PX,
          bold: true,
          lineSpacing: 1.25,
        })),
      ];
    case "textFigureLeft":
      return [standardTitle, { type: "body", index: 0, text: archetype.body, position: { left: 714, top: 206, width: 490, height: 230 }, fontSize: SUBHEAD_PX, lineSpacing: 1.28 }];
    case "figureTextRight":
      return [standardTitle, { type: "body", index: 0, text: archetype.body, position: { left: 76, top: 206, width: 490, height: 230 }, fontSize: SUBHEAD_PX, lineSpacing: 1.28 }];
    case "fullFigure":
      return [standardTitle, { type: "body", index: 0, text: archetype.body, position: { left: 76, top: 578, width: 1128, height: 62 }, fontSize: 19, lineSpacing: 1.1 }];
    case "chart":
    case "table":
      return [standardTitle, { type: "body", index: 0, text: archetype.body, position: { left: 76, top: 145, width: 1040, height: 46 }, fontSize: 19 }];
    case "metrics":
      return [
        standardTitle,
        ...archetype.bodies.map((text, index) => ({
          type: "content",
          index,
          text,
          position: { left: 72 + index * 384, top: 246, width: 320, height: 190 },
          fontSize: 42,
          bold: true,
          lineSpacing: 1.02,
        })),
      ];
    case "technical":
      return [standardTitle, { type: "body", index: 0, text: archetype.body, position: { left: 76, top: 145, width: 1040, height: 58 }, fontSize: 19 }];
    case "quote":
      return [
        standardTitle,
        { type: "body", index: 0, text: archetype.body, position: { left: 146, top: 235, width: 980, height: 230 }, fontSize: 38, lineSpacing: 1.14 },
      ];
    case "closing":
      return [
        { ...standardTitle, position: { left: 730, top: 250, width: 440, height: 110 }, fontSize: COVER_PX, alignment: "center" },
        { type: "subtitle", index: 0, text: archetype.body, position: { left: 720, top: 390, width: 460, height: 120 }, fontSize: SUBHEAD_PX, alignment: "center", lineSpacing: 1.2 },
      ];
    default:
      throw new Error(`Unsupported archetype kind: ${archetype.kind}`);
  }
}

function addIndexSlide(presentation, theme, assets, indexLayout) {
  const slide = presentation.slides.add();
  slide.setLayout(indexLayout);
  slide.background.fill = theme.surface;
  addBrandPlane(slide, theme, { left: 1030, top: -70, width: 300, height: 860 });
  addText(slide, "index-title", `${theme.name} theme · layout index`, { left: 72, top: 54, width: 850, height: 86 }, {
    typeface: TITLE_FACE,
    fontSize: TITLE_PX,
    bold: true,
    color: theme.onSurface,
    lineSpacing: 0.96,
  });
  addText(slide, "index-intro", "Duplicate an exemplar or apply its named layout. Every theme uses identical geometry.", { left: 76, top: 136, width: 760, height: 64 }, {
    fontSize: BODY_PX,
    color: theme.secondary,
  });
  const left = ARCHETYPES.slice(0, 9).map((item, index) => `${String(index + 2).padStart(2, "0")}  ${item.layoutName.replace(/^Stevens \d+ — /, "")}`).join("\n");
  const right = ARCHETYPES.slice(9).map((item, index) => `${String(index + 11).padStart(2, "0")}  ${item.layoutName.replace(/^Stevens \d+ — /, "")}`).join("\n");
  addText(slide, "index-left", left, { left: 76, top: 226, width: 440, height: 350 }, { fontSize: BODY_PX, color: theme.onSurface, lineSpacing: 1.34 });
  addText(slide, "index-right", right, { left: 558, top: 226, width: 440, height: 350 }, { fontSize: BODY_PX, color: theme.onSurface, lineSpacing: 1.34 });
  addLogo(slide, theme, assets, { left: 870, top: 66, width: 96, height: 117 });
  addPageFooter(slide, theme, 1, assets, { showStar: false });
  setNotes(slide, false);
}

function setNotes(slide, usesCampus) {
  const lines = [
    "[Sources]",
    "- Stevens Institute of Technology Visual Identity Guide (2023), supplied brand resource.",
    "- Stevens PowerPoint Template Guide (2022), supplied presentation resource.",
  ];
  if (usesCampus) lines.push("- Stevens campus-view photograph (2022), supplied brand resource.");
  lines.push("- Example copy and data are illustrative; replace before presenting.");
  slide.speakerNotes.textFrame.setText(lines);
  slide.speakerNotes.setVisible(true);
}

function addArchetypeVisual(slide, archetype, theme, assets, pageNumber) {
  slide.background.fill = theme.surface;
  let usesCampus = false;
  switch (archetype.kind) {
    case "textCover":
      addBrandPlane(slide, theme, { left: 930, top: -80, width: 430, height: 860 });
      addLogo(slide, theme, assets, { left: 820, top: 48, width: 105, height: 128 });
      addLine(slide, "cover-rule", 76, 535, 710, theme.series[0], 3);
      break;
    case "imageCover":
      usesCampus = true;
      slide.images.add({ blob: assets.campus, contentType: "image/png", alt: "Stevens campus and Manhattan skyline", fit: "cover", position: { left: 610, top: 0, width: 670, height: 720 }, crop: { left: 0.08, top: 0, right: 0.02, bottom: 0 } });
      addShape(slide, "image-cover-divider", "parallelogram", { left: 540, top: -40, width: 150, height: 800 }, theme.brandPlane);
      addLogo(slide, theme, assets, { left: 75, top: 55, width: 92, height: 112 });
      break;
    case "roadmap": {
      addLine(slide, "roadmap-line", 120, 432, 1010, theme.secondary, 2);
      const labels = ["DISCOVER", "DEFINE", "DEVELOP", "DELIVER"];
      labels.forEach((label, index) => {
        const x = 100 + index * 292;
        addShape(slide, `roadmap-node-${index + 1}`, "rect", { left: x, top: 416, width: 32, height: 32 }, theme.series[index % 3]);
        addText(slide, `roadmap-label-${index + 1}`, label, { left: x - 8, top: 468, width: 165, height: 38 }, { fontSize: 20, bold: true, color: theme.onSurface });
        addText(slide, `roadmap-copy-${index + 1}`, ["Find the signal", "Set the criteria", "Test the idea", "Make it useful"][index], { left: x - 8, top: 512, width: 190, height: 48 }, { fontSize: 17, color: theme.secondary });
      });
      addPageFooter(slide, theme, pageNumber, assets);
      break;
    }
    case "sectionDivider":
      addBrandPlane(slide, theme, { left: -170, top: -50, width: 440, height: 830 });
      addText(slide, "section-number", "01", { left: 54, top: 220, width: 150, height: 175 }, { typeface: TITLE_FACE, fontSize: 118, bold: true, color: "#FFFFFF", alignment: "center", lineSpacing: 0.9 });
      addLine(slide, "section-rule", 344, 478, 790, theme.series[0], 3);
      addPageFooter(slide, theme, pageNumber, assets, { offset: 230 });
      break;
    case "keyMessage":
      addLine(slide, "key-message-rule", 126, 472, 720, theme.series[0], 4);
      addText(slide, "key-message-label", "KEY MESSAGE", { left: 126, top: 500, width: 240, height: 34 }, { fontSize: 16, bold: true, color: theme.secondary });
      addPageFooter(slide, theme, pageNumber, assets);
      break;
    case "titleBody": {
      addShape(slide, "body-accent", "rect", { left: 72, top: 190, width: 8, height: 300 }, theme.series[0]);
      const bulletText = [
        { bulletCharacter: "•", marginLeft: 24, indent: -12, runs: ["Make one audience-facing claim per slide."] },
        { bulletCharacter: "•", marginLeft: 24, indent: -12, runs: ["Use evidence to explain what the claim means."] },
        { bulletCharacter: "•", marginLeft: 24, indent: -12, runs: ["End with the consequence or next action."] },
      ];
      const bullets = addShape(slide, "body-bullets", "textbox", { left: 98, top: 366, width: 790, height: 172 }, "none");
      bullets.text = bulletText;
      bullets.text.style = { typeface: BODY_FACE, fontSize: BODY_PX, color: theme.onSurface, lineSpacing: 1.35, insets: { top: 0, right: 0, bottom: 0, left: 0 }, autoFit: "none", wrap: "square" };
      addText(slide, "body-callout", "ONE SLIDE\nONE PRIMARY CLAIM", { left: 940, top: 216, width: 260, height: 120 }, { typeface: TITLE_FACE, fontSize: 32, bold: true, color: theme.series[0], lineSpacing: 1 });
      addPageFooter(slide, theme, pageNumber, assets);
      break;
    }
    case "twoColumn":
      addLine(slide, "column-divider", 640, 190, 0, theme.secondary, 2).position = { left: 640, top: 190, width: 0, height: 350 };
      addText(slide, "left-label", "WHAT WE KNOW", { left: 76, top: 525, width: 250, height: 30 }, { fontSize: 15, bold: true, color: theme.series[0] });
      addText(slide, "right-label", "WHAT IT MEANS", { left: 704, top: 525, width: 250, height: 30 }, { fontSize: 15, bold: true, color: theme.series[1] });
      addPageFooter(slide, theme, pageNumber, assets);
      break;
    case "threePoint":
      for (let index = 0; index < 3; index += 1) {
        addShape(slide, `point-rule-${index + 1}`, "rect", { left: 72 + index * 384, top: 206, width: 110, height: 8 }, theme.series[index]);
        addText(slide, `point-detail-${index + 1}`, ["Clarify scope and stakes.", "Show the pattern and source.", "Name the owner and timing."][index], { left: 72 + index * 384, top: 470, width: 320, height: 72 }, { fontSize: 18, color: theme.secondary, lineSpacing: 1.2 });
      }
      addPageFooter(slide, theme, pageNumber, assets);
      break;
    case "textFigureLeft":
      usesCampus = true;
      slide.images.add({ blob: assets.campus, contentType: "image/png", alt: "Stevens campus and Manhattan skyline", fit: "cover", position: { left: 72, top: 198, width: 560, height: 340 }, crop: { left: 0.18, top: 0.04, right: 0.04, bottom: 0.03 } });
      addShape(slide, "figure-caption-band", "rect", { left: 72, top: 508, width: 560, height: 30 }, theme.brandPlane);
      addText(slide, "figure-caption", "Campus context · example evidence frame", { left: 86, top: 512, width: 530, height: 22 }, { fontSize: 14, bold: true, color: "#FFFFFF", lineSpacing: 1 });
      addPageFooter(slide, theme, pageNumber, assets, { showStar: false, showWordmark: false });
      break;
    case "figureTextRight":
      usesCampus = true;
      slide.images.add({ blob: assets.campus, contentType: "image/png", alt: "Stevens campus and Manhattan skyline", fit: "cover", position: { left: 648, top: 198, width: 560, height: 340 }, crop: { left: 0.18, top: 0.04, right: 0.04, bottom: 0.03 } });
      addShape(slide, "figure-right-caption-band", "rect", { left: 648, top: 508, width: 560, height: 30 }, theme.brandPlane);
      addText(slide, "figure-right-caption", "Campus context · example evidence frame", { left: 662, top: 512, width: 530, height: 22 }, { fontSize: 14, bold: true, color: "#FFFFFF", lineSpacing: 1 });
      addPageFooter(slide, theme, pageNumber, assets, { showStar: false, showWordmark: false });
      break;
    case "fullFigure":
      usesCampus = true;
      slide.images.add({ blob: assets.campus, contentType: "image/png", alt: "Stevens campus and Manhattan skyline", fit: "cover", position: { left: 72, top: 164, width: 1136, height: 382 }, crop: { left: 0.18, top: 0.02, right: 0.02, bottom: 0.03 } });
      addShape(slide, "full-figure-identifier-tab", "rect", { left: 108, top: 160, width: 145, height: 112 }, "#A32638");
      slide.images.add({
        blob: assets.logoNegative,
        contentType: "image/png",
        alt: "Official Stevens negative identifier",
        fit: "contain",
        position: { left: 126, top: 168, width: 74, height: 90 },
      });
      addShape(slide, "full-figure-accent", "rect", { left: 72, top: 546, width: 1136, height: 8 }, theme.series[0]);
      addPageFooter(slide, theme, pageNumber, assets, { showStar: false, showWordmark: false });
      break;
    case "chart":
      slide.charts.add("bar", {
        position: { left: 96, top: 208, width: 1060, height: 360 },
        categories: ["Baseline", "Prototype", "Target"],
        series: [{
          name: "Illustrative result",
          values: [42, 67, 86],
          fill: theme.series[0],
          points: theme.series.map((fill, idx) => ({ idx, fill })),
        }],
        barOptions: { direction: "bar", grouping: "clustered", gapWidth: 62 },
        hasLegend: false,
        xAxis: { visible: false, majorGridlines: null, minorGridlines: null },
        yAxis: { textStyle: { fill: theme.onSurface, fontSize: 17 }, line: { style: "solid", fill: theme.secondary, width: 1 }, majorGridlines: null },
        dataLabels: { showValue: true, position: "outEnd", textStyle: { fill: theme.onSurface, fontSize: 18, bold: true } },
        chartFill: theme.surface,
        chartLine: { style: "solid", fill: "none", width: 0 },
        plotAreaFill: theme.surface,
        plotAreaLine: { style: "solid", fill: "none", width: 0 },
      });
      // LibreOffice does not consistently preserve category-label styling from
      // chart XML. Mask that renderer-controlled strip and provide accessible,
      // theme-aware direct labels so Dark never inherits gray text.
      addShape(slide, "chart-category-label-mask", "rect", { left: 70, top: 218, width: 104, height: 332 }, theme.surface);
      [
        ["Target", 250],
        ["Prototype", 360],
        ["Baseline", 468],
      ].forEach(([label, top]) => {
        addText(slide, `chart-category-${label.toLowerCase()}`, label, { left: 76, top, width: 88, height: 32 }, {
          fontSize: 15,
          bold: true,
          color: theme.onSurface,
          alignment: "right",
          verticalAlignment: "middle",
          lineSpacing: 1,
        });
      });
      addText(slide, "chart-summary", "Illustrative takeaway: the target is 2× the baseline.", { left: 832, top: 578, width: 350, height: 34 }, { fontSize: 16, bold: true, color: theme.series[0], alignment: "right" });
      addPageFooter(slide, theme, pageNumber, assets);
      break;
    case "table": {
      const table = slide.tables.add({
        rows: 5,
        columns: 4,
        left: 82,
        top: 214,
        width: 1116,
        height: 330,
        values: [
          ["Option", "Quality", "Speed", "Decision"],
          ["Baseline", "Good", "1.0×", "Reference"],
          ["Approach A", "Better", "1.7×", "Consider"],
          ["Approach B", "Best", "2.4×", "Preferred"],
          ["Constraint", "Illustrative", "Illustrative", "Validate"],
        ],
      });
      table.borders.assign({ style: "solid", fill: theme.secondary, width: 1 });
      table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 4 }).assign({
        fill: theme.brandPlane,
        textStyle: { typeface: BODY_FACE, fontSize: 18, bold: true, color: "#FFFFFF" },
        margins: { top: 8, right: 8, bottom: 8, left: 8 },
      });
      table.cells.block({ row: 1, column: 0, rowCount: 4, columnCount: 4 }).assign({
        fill: theme.surface,
        textStyle: { typeface: BODY_FACE, fontSize: 17, color: theme.onSurface },
        margins: { top: 8, right: 8, bottom: 8, left: 8 },
      });
      table.cells.block({ row: 3, column: 0, rowCount: 1, columnCount: 4 }).assign({
        fill: theme.name === "Dark" ? "#004380" : "#E7F2FB",
        textStyle: { typeface: BODY_FACE, fontSize: 17, bold: true, color: theme.name === "Dark" ? "#FFFFFF" : "#363D45" },
      });
      addPageFooter(slide, theme, pageNumber, assets);
      break;
    }
    case "metrics":
      for (let index = 0; index < 3; index += 1) {
        addShape(slide, `metric-rule-${index + 1}`, "rect", { left: 72 + index * 384, top: 218, width: 96, height: 8 }, theme.series[index]);
        if (index < 2) addLine(slide, `metric-divider-${index + 1}`, 420 + index * 384, 236, 0, theme.secondary, 1).position = { left: 420 + index * 384, top: 236, width: 0, height: 230 };
      }
      addText(slide, "metric-note", "Illustrative metrics · define numerator, denominator, period, and source in speaker notes.", { left: 76, top: 520, width: 930, height: 42 }, { fontSize: 17, color: theme.secondary });
      addPageFooter(slide, theme, pageNumber, assets);
      break;
    case "technical": {
      const connectorColor = theme.secondary;
      addLine(slide, "technical-connector-1", 330, 390, 150, connectorColor, 3);
      addLine(slide, "technical-connector-2", 700, 390, 150, connectorColor, 3);
      const nodes = [
        { x: 110, label: "INPUT\nSourced data" },
        { x: 480, label: "SYSTEM\nValidated logic" },
        { x: 850, label: "OUTPUT\nDecision-ready result" },
      ];
      nodes.forEach((node, index) => {
        addShape(slide, `technical-node-${index + 1}`, "rect", { left: node.x, top: 316, width: 220, height: 150 }, theme.nodeFill, { style: "solid", fill: theme.series[index], width: 3 });
        addText(slide, `technical-node-label-${index + 1}`, node.label, { left: node.x + 22, top: 352, width: 176, height: 84 }, { fontSize: 21, bold: true, color: theme.nodeText, alignment: "center", verticalAlignment: "middle", lineSpacing: 1.15 });
      });
      addText(slide, "technical-contract", "Label interfaces, assumptions, and failure paths in speaker notes or an appendix.", { left: 234, top: 514, width: 812, height: 38 }, { fontSize: 17, color: theme.secondary, alignment: "center" });
      addPageFooter(slide, theme, pageNumber, assets);
      break;
    }
    case "quote":
      addLine(slide, "quote-rule", 146, 504, 560, theme.series[0], 4);
      addText(slide, "quote-source-note", "Always include the original source in speaker notes.", { left: 146, top: 530, width: 600, height: 32 }, { fontSize: 16, color: theme.secondary });
      addPageFooter(slide, theme, pageNumber, assets);
      break;
    case "closing":
      addBrandPlane(slide, theme, { left: -170, top: -70, width: 720, height: 860 });
      addLogo(slide, theme, assets, { left: 800, top: 76, width: 105, height: 128 });
      addLine(slide, "closing-rule", 96, 644, 1010, theme.secondary, 2);
      break;
    default:
      throw new Error(`Unsupported visual kind: ${archetype.kind}`);
  }
  setNotes(slide, usesCampus);
}

function setThemeScheme(presentation, theme) {
  presentation.theme.colorScheme = {
    name: `Stevens ${theme.name}`,
    themeColors: {
      accent1: theme.series[0],
      accent2: theme.series[1],
      accent3: theme.series[2],
      accent4: "#E7842E",
      accent5: "#E7F2FB",
      accent6: "#FFFAE6",
      bg1: theme.surface,
      bg2: theme.subtle,
      tx1: theme.onSurface,
      tx2: theme.secondary,
      dk1: "#363D45",
      dk2: "#004380",
      lt1: "#FFFFFF",
      lt2: "#E4E5E6",
      hlink: "#4896CF",
      folHlink: "#E7842E",
    },
  };
}

async function exportDeckArtifacts(presentation, outputPath, qaPath, metadata) {
  await fs.mkdir(qaPath, { recursive: true });
  const inspect = await presentation.inspect({ kind: "deck,slide,textbox,shape,image,table,chart,notes,layout", maxChars: 100000 });
  await fs.writeFile(path.join(qaPath, "inspect.ndjson"), inspect.ndjson);
  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(path.join(qaPath, `${stem}.png`), await presentation.export({ slide, format: "png", scale: 1 }));
    await fs.writeFile(path.join(qaPath, `${stem}.layout.json`), await (await slide.export({ format: "layout" })).text());
  }
  await writeBlob(path.join(qaPath, "montage.webp"), await presentation.export({ format: "webp", montage: { columns: 3, slideWidth: 480, gap: 16, padding: 16, background: "#FFFFFF" }, scale: 1 }));
  await fs.writeFile(path.join(qaPath, "structure.json"), JSON.stringify(metadata, null, 2));
  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(outputPath);
}

async function loadSource(sourcePath) {
  const presentation = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
  presentation.comments.replaceFromProto({ people: [], threads: [] });
  return presentation;
}

async function buildThemeDeck(sourcePath, outputDir, qaDir, themeKey, assets) {
  const theme = THEMES[themeKey];
  const presentation = await loadSource(sourcePath);
  const sourceCounts = {
    slides: presentation.slides.items.length,
    masters: presentation.masters.items.length,
    layouts: presentation.layouts.items.length,
  };
  for (const slide of [...presentation.slides.items]) slide.delete();
  presentation.view.hideGridlines();
  presentation.view.hideGuides();
  setThemeScheme(presentation, theme);
  const master = presentation.masters.add(`Stevens ${theme.name} Master`);
  master.background.fill = theme.surface;
  const indexLayout = presentation.layouts.add("Stevens — Theme Index");
  indexLayout.setParentLayoutId(master.id);
  const layouts = new Map();
  for (const archetype of ARCHETYPES) {
    const layout = presentation.layouts.add(archetype.layoutName);
    layout.setParentLayoutId(master.id);
    for (const spec of layoutPlaceholders(archetype)) addPlaceholder(layout, spec, theme);
    layouts.set(archetype.id, layout);
  }
  addIndexSlide(presentation, theme, assets, indexLayout);
  for (const [index, archetype] of ARCHETYPES.entries()) {
    const slide = presentation.slides.add();
    slide.setLayout(layouts.get(archetype.id));
    for (const spec of layoutPlaceholders(archetype)) addSlidePlaceholder(slide, spec, theme);
    addArchetypeVisual(slide, archetype, theme, assets, index + 2);
  }
  const outputPath = path.join(outputDir, `Stevens-Presentation-Template-${theme.name}.pptx`);
  await exportDeckArtifacts(presentation, outputPath, path.join(qaDir, themeKey), {
    theme: themeKey,
    sourceCounts,
    finalCounts: {
      slides: presentation.slides.items.length,
      masters: presentation.masters.items.length,
      layouts: presentation.layouts.items.length,
    },
    customMaster: master.name,
    customLayouts: ARCHETYPES.map((item) => item.layoutName),
  });
}

function addGalleryThemeSlide(presentation, theme, assets, pageNumber, galleryLayout) {
  const slide = presentation.slides.add();
  slide.setLayout(galleryLayout);
  slide.background.fill = theme.surface;
  addBrandPlane(slide, theme, { left: 950, top: -60, width: 390, height: 840 });
  addLogo(slide, theme, assets, theme.name === "Dark" ? { left: 1080, top: 50, width: 98, height: 120 } : { left: 820, top: 50, width: 98, height: 120 });
  addText(slide, `gallery-${theme.name}-eyebrow`, `${theme.name.toUpperCase()} THEME`, { left: 76, top: 86, width: 300, height: 36 }, { fontSize: 16, bold: true, color: theme.series[0] });
  addText(slide, `gallery-${theme.name}-title`, "One geometry,\none semantic map", { left: 72, top: 145, width: 780, height: 155 }, { typeface: TITLE_FACE, fontSize: COVER_PX, bold: true, color: theme.onSurface, lineSpacing: 0.96 });
  addText(slide, `gallery-${theme.name}-body`, theme.name === "White" ? "Default for general presentations and research updates." : "Best for technical systems talks and high-contrast rooms.", { left: 76, top: 325, width: 690, height: 84 }, { fontSize: SUBHEAD_PX, color: theme.secondary, lineSpacing: 1.2 });
  theme.series.forEach((color, index) => addShape(slide, `gallery-${theme.name}-swatch-${index + 1}`, "rect", { left: 76 + index * 148, top: 452, width: 118, height: 72 }, color));
  addText(slide, `gallery-${theme.name}-rule`, "Saira Condensed 54 pt\nIBM Plex Sans 18 pt", { left: 76, top: 558, width: 500, height: 80 }, { fontSize: BODY_PX, color: theme.onSurface, lineSpacing: 1.25 });
  addPageFooter(slide, theme, pageNumber, assets, { showStar: false });
  setNotes(slide, false);
}

async function buildGallery(sourcePath, outputDir, qaDir, assets) {
  const presentation = await loadSource(sourcePath);
  const sourceCounts = { slides: presentation.slides.items.length, masters: presentation.masters.items.length, layouts: presentation.layouts.items.length };
  for (const slide of [...presentation.slides.items]) slide.delete();
  presentation.view.hideGridlines();
  presentation.view.hideGuides();
  setThemeScheme(presentation, THEMES.white);
  const galleryMaster = presentation.masters.add("Stevens Gallery Master");
  galleryMaster.background.fill = "#FFFFFF";
  const galleryLayout = presentation.layouts.add("Stevens — Gallery Canvas");
  galleryLayout.setParentLayoutId(galleryMaster.id);
  const intro = presentation.slides.add();
  intro.setLayout(galleryLayout);
  intro.background.fill = "#FFFFFF";
  addText(intro, "gallery-title", "Stevens Presentation\nThemes", { left: 72, top: 78, width: 860, height: 150 }, { typeface: TITLE_FACE, fontSize: COVER_PX, bold: true, color: "#363D45", lineSpacing: 0.96 });
  addText(intro, "gallery-subtitle", "White and Dark share identical 16:9 geometry and 17 reusable archetypes.", { left: 76, top: 245, width: 830, height: 70 }, { fontSize: SUBHEAD_PX, color: "#7F7F7F" });
  const blocks = [THEMES.white, THEMES.dark];
  blocks.forEach((theme, index) => {
    const x = 196 + index * 488;
    addShape(intro, `gallery-plane-${index + 1}`, "rect", { left: x, top: 350, width: 400, height: 200 }, theme.surface, { style: "solid", fill: index === 0 ? "#E4E5E6" : theme.surface, width: index === 0 ? 2 : 0 });
    addText(intro, `gallery-label-${index + 1}`, theme.name.toUpperCase(), { left: x + 28, top: 388, width: 320, height: 56 }, { typeface: TITLE_FACE, fontSize: 38, bold: true, color: theme.onSurface });
    addText(intro, `gallery-detail-${index + 1}`, index === 0 ? "Default" : "Technical", { left: x + 28, top: 474, width: 320, height: 38 }, { fontSize: 18, color: theme.secondary });
  });
  addLogo(intro, THEMES.white, assets, { left: 1082, top: 54, width: 96, height: 117 });
  addPageFooter(intro, THEMES.white, 1, assets, { showStar: false });
  setNotes(intro, false);
  addGalleryThemeSlide(presentation, THEMES.white, assets, 2, galleryLayout);
  addGalleryThemeSlide(presentation, THEMES.dark, assets, 3, galleryLayout);
  const map = presentation.slides.add();
  map.setLayout(galleryLayout);
  map.background.fill = "#FFFFFF";
  addText(map, "map-title", "The same content can change themes without reflow", { left: 72, top: 54, width: 980, height: 95 }, { typeface: TITLE_FACE, fontSize: TITLE_PX, bold: true, color: "#363D45", lineSpacing: 0.96 });
  blocks.forEach((theme, index) => {
    const x = 180 + index * 520;
    addShape(map, `map-surface-${index + 1}`, "rect", { left: x, top: 200, width: 400, height: 330 }, theme.surface, { style: "solid", fill: index === 0 ? "#E4E5E6" : theme.surface, width: index === 0 ? 2 : 0 });
    addShape(map, `map-accent-${index + 1}`, "rect", { left: x + 32, top: 228, width: 104, height: 8 }, theme.series[0]);
    addText(map, `map-heading-${index + 1}`, "Same claim", { left: x + 32, top: 262, width: 316, height: 62 }, { typeface: TITLE_FACE, fontSize: 32, bold: true, color: theme.onSurface });
    addText(map, `map-body-${index + 1}`, "Same title, body measure, and evidence frame.", { left: x + 32, top: 345, width: 316, height: 88 }, { fontSize: 18, color: theme.secondary, lineSpacing: 1.2 });
    addText(map, `map-label-${index + 1}`, theme.name.toUpperCase(), { left: x + 32, top: 478, width: 316, height: 30 }, { fontSize: 15, bold: true, color: theme.series[0] });
  });
  addPageFooter(map, THEMES.white, 4, assets);
  setNotes(map, false);
  await exportDeckArtifacts(presentation, path.join(outputDir, "Stevens-Presentation-Themes-Gallery.pptx"), path.join(qaDir, "gallery"), {
    theme: "gallery",
    sourceCounts,
    finalCounts: { slides: presentation.slides.items.length, masters: presentation.masters.items.length, layouts: presentation.layouts.items.length },
  });
}

async function main() {
  const args = parseArgs(process.argv);
  const sourcePath = path.resolve(args.source);
  const assetDir = path.resolve(args["asset-dir"]);
  const outputDir = path.resolve(args["output-dir"]);
  const qaDir = path.resolve(args["qa-dir"]);
  await fs.mkdir(outputDir, { recursive: true });
  await fs.mkdir(qaDir, { recursive: true });
  const assets = {
    logoPositive: await readBytes(path.join(assetDir, "brand", "stevens-identifier-positive.png")),
    logoNegative: await readBytes(path.join(assetDir, "brand", "stevens-identifier-negative.png")),
    star: await readBytes(path.join(assetDir, "brand", "stevens-star-gold.png")),
    campus: await readBytes(path.join(assetDir, "brand", "campus-view.png")),
  };
  for (const themeKey of ["white", "dark"]) {
    await buildThemeDeck(sourcePath, outputDir, qaDir, themeKey, assets);
  }
  await buildGallery(sourcePath, outputDir, qaDir, assets);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
