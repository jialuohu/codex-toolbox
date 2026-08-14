#!/usr/bin/env python3
"""Validate the Stevens presentation template bundle and its stable contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_R_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"p": P_NS, "a": A_NS, "r": R_NS, "rel": PKG_R_NS}

THEME_FILES = {
    "white": "Stevens-Presentation-Template-White.pptx",
    "dark": "Stevens-Presentation-Template-Dark.pptx",
}
GALLERY_FILE = "Stevens-Presentation-Themes-Gallery.pptx"
ACTUAL_CONTENT_PART = re.compile(
    r"^ppt/(?:slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml$"
)
BANNED_EFFECT_TAGS = {
    f"{{{A_NS}}}gradFill",
    f"{{{A_NS}}}outerShdw",
    f"{{{A_NS}}}innerShdw",
    f"{{{A_NS}}}prstShdw",
}
TEXT_PROPERTY_TAGS = {
    f"{{{A_NS}}}rPr",
    f"{{{A_NS}}}defRPr",
    f"{{{A_NS}}}endParaRPr",
}
OFF_TAG = f"{{{A_NS}}}off"
EXT_TAG = f"{{{A_NS}}}ext"


class ValidationError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def numbered_parts(names: list[str], prefix: str) -> list[str]:
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)\.xml$")
    matches = []
    for name in names:
        match = pattern.match(name)
        if match:
            matches.append((int(match.group(1)), name))
    return [name for _, name in sorted(matches)]


def parse_xml(archive: ZipFile, name: str) -> ET.Element:
    return ET.fromstring(archive.read(name))


def element_text(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.findall(".//a:t", NS)).strip()


def layout_names(archive: ZipFile, names: list[str]) -> dict[str, str]:
    result = {}
    for name in numbered_parts(names, "ppt/slideLayouts/slideLayout"):
        root = parse_xml(archive, name)
        common = root.find("p:cSld", NS)
        result[name] = "" if common is None else common.get("name", "")
    return result


def slide_layout_part(archive: ZipFile, slide_number: int) -> str:
    rels_name = f"ppt/slides/_rels/slide{slide_number}.xml.rels"
    root = parse_xml(archive, rels_name)
    for relationship in root.findall("rel:Relationship", NS):
        if relationship.get("Type", "").endswith("/slideLayout"):
            target = relationship.get("Target", "")
            if target.startswith("/"):
                return posixpath.normpath(target).lstrip("/")
            return posixpath.normpath(posixpath.join("ppt/slides", target))
    raise ValidationError(f"slide {slide_number} has no layout relationship")


def geometry_signature(root: ET.Element) -> tuple[tuple[str, str, str], ...]:
    signature = []
    for element in root.iter():
        if element.tag == OFF_TAG:
            signature.append(("off", element.get("x", ""), element.get("y", "")))
        elif element.tag == EXT_TAG:
            signature.append(("ext", element.get("cx", ""), element.get("cy", "")))
    return tuple(signature)


def named_shape(root: ET.Element, name: str) -> ET.Element | None:
    for shape_tree in root.findall(".//p:spTree", NS):
        for shape in list(shape_tree):
            properties = shape.find(".//p:cNvPr", NS)
            if properties is not None and properties.get("name") == name:
                return shape
    return None


def shape_bounds(shape: ET.Element) -> tuple[int, int, int, int] | None:
    transform = shape.find(".//a:xfrm", NS)
    if transform is None:
        return None
    offset = transform.find("a:off", NS)
    extent = transform.find("a:ext", NS)
    if offset is None or extent is None:
        return None
    return (
        int(offset.get("x", "0")),
        int(offset.get("y", "0")),
        int(extent.get("cx", "0")),
        int(extent.get("cy", "0")),
    )


def validate_footer_alignment(archive: ZipFile, names: list[str]) -> None:
    checked = 0
    for slide_number, part in enumerate(
        numbered_parts(names, "ppt/slides/slide"),
        start=1,
    ):
        root = parse_xml(archive, part)
        page = named_shape(root, f"page-number-{slide_number}")
        rule = named_shape(root, f"footer-rule-{slide_number}")
        wordmark = named_shape(root, f"footer-wordmark-{slide_number}")
        if page is None and rule is None and wordmark is None:
            continue
        if page is None or rule is None:
            raise ValidationError(f"slide {slide_number} footer is structurally incomplete")
        page_bounds = shape_bounds(page)
        rule_bounds = shape_bounds(rule)
        if page_bounds is None or rule_bounds is None:
            raise ValidationError(f"slide {slide_number} footer has no usable transform")
        page_center = page_bounds[1] + page_bounds[3] / 2
        rule_center = rule_bounds[1] + rule_bounds[3] / 2
        if not math.isclose(page_center, rule_center, abs_tol=1):
            raise ValidationError(
                f"slide {slide_number} page number is not centered on the footer rule"
            )
        page_body = page.find(".//a:bodyPr", NS)
        if page_body is None or page_body.get("anchor") != "ctr":
            raise ValidationError(f"slide {slide_number} page number is not vertically centered")
        if wordmark is not None:
            wordmark_bounds = shape_bounds(wordmark)
            if wordmark_bounds is None:
                raise ValidationError(f"slide {slide_number} wordmark has no usable transform")
            wordmark_center = wordmark_bounds[1] + wordmark_bounds[3] / 2
            if not math.isclose(wordmark_center, rule_center, abs_tol=1):
                raise ValidationError(
                    f"slide {slide_number} wordmark is not centered on the footer rule"
                )
            wordmark_body = wordmark.find(".//a:bodyPr", NS)
            if wordmark_body is None or wordmark_body.get("anchor") != "ctr":
                raise ValidationError(f"slide {slide_number} wordmark is not vertically centered")
        checked += 1
    if checked == 0:
        raise ValidationError("presentation has no named footers to validate")


def validate_checksums(skill_root: Path, checksum_path: Path) -> None:
    payload = json.loads(checksum_path.read_text(encoding="utf-8"))
    if payload.get("algorithm") != "sha256":
        raise ValidationError("asset checksum algorithm must be sha256")
    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValidationError("asset checksum file has no entries")

    expected_paths = set()
    for entry in entries:
        relative = entry.get("path", "")
        expected_paths.add(relative)
        path = skill_root / relative
        if not path.is_file():
            raise ValidationError(f"checksummed asset is missing: {relative}")
        if path.stat().st_size != entry.get("bytes"):
            raise ValidationError(f"asset size mismatch: {relative}")
        if sha256_file(path) != entry.get("sha256"):
            raise ValidationError(f"asset checksum mismatch: {relative}")

    actual_paths = {
        path.relative_to(skill_root).as_posix()
        for path in (skill_root / "assets").rglob("*")
        if path.is_file() and not path.name.endswith(".inspect.ndjson")
    }
    if expected_paths != actual_paths:
        missing = sorted(actual_paths - expected_paths)
        stale = sorted(expected_paths - actual_paths)
        raise ValidationError(f"checksum inventory mismatch; missing={missing}, stale={stale}")


def validate_slide_size(archive: ZipFile) -> None:
    root = parse_xml(archive, "ppt/presentation.xml")
    size = root.find("p:sldSz", NS)
    if size is None:
        raise ValidationError("presentation has no slide size")
    width = int(size.get("cx", "0"))
    height = int(size.get("cy", "0"))
    if width <= 0 or height <= 0 or not math.isclose(width / height, 16 / 9, rel_tol=0.001):
        raise ValidationError(f"presentation is not 16:9: {width}x{height}")


def validate_effects_and_opacity(archive: ZipFile, names: list[str]) -> None:
    for name in names:
        if not ACTUAL_CONTENT_PART.match(name):
            continue
        root = parse_xml(archive, name)
        for element in root.iter():
            if element.tag in BANNED_EFFECT_TAGS:
                raise ValidationError(f"gradient or shadow found in {name}")
            if element.tag == f"{{{A_NS}}}alpha":
                value = int(element.get("val", "100000"))
                if value < 85000:
                    raise ValidationError(f"opacity below 85% found in {name}")


def validate_fonts(archive: ZipFile, names: list[str]) -> None:
    content = b"".join(
        archive.read(name)
        for name in names
        if ACTUAL_CONTENT_PART.match(name)
    )
    for family in (b"Saira Condensed", b"IBM Plex Sans"):
        if family not in content:
            raise ValidationError(f"presentation does not reference {family.decode()}")


def validate_notes(archive: ZipFile, names: list[str], expected_count: int) -> None:
    note_parts = numbered_parts(names, "ppt/notesSlides/notesSlide")
    if len(note_parts) != expected_count:
        raise ValidationError(f"expected {expected_count} notes slides, found {len(note_parts)}")
    for index, name in enumerate(note_parts, start=1):
        if "[Sources]" not in element_text(parse_xml(archive, name)):
            raise ValidationError(f"slide {index} notes are missing [Sources]")


def validate_custom_placeholders(
    archive: ZipFile,
    layout_by_part: dict[str, str],
    required_layouts: set[str],
) -> None:
    names_to_parts = {name: part for part, name in layout_by_part.items()}
    missing = sorted(required_layouts - set(names_to_parts))
    if missing:
        raise ValidationError(f"missing named layouts: {missing}")
    for layout_name in sorted(required_layouts):
        root = parse_xml(archive, names_to_parts[layout_name])
        placeholder_shapes = [
            shape for shape in root.findall(".//p:sp", NS)
            if shape.find(".//p:ph", NS) is not None
        ]
        if not placeholder_shapes:
            raise ValidationError(f"layout has no true placeholder: {layout_name}")
        for shape in placeholder_shapes:
            if not element_text(shape):
                raise ValidationError(f"layout has an empty structural placeholder: {layout_name}")


def validate_text_color_rule(archive: ZipFile, names: list[str], forbidden: str) -> None:
    forbidden = forbidden.upper().lstrip("#")
    for name in names:
        if not re.match(r"^ppt/slides/slide\d+\.xml$", name):
            continue
        root = parse_xml(archive, name)
        for element in root.iter():
            if element.tag not in TEXT_PROPERTY_TAGS:
                continue
            for color in element.findall(".//a:srgbClr", NS):
                if color.get("val", "").upper() == forbidden:
                    raise ValidationError(f"forbidden text color #{forbidden} found in {name}")


def validate_brand_media(archive: ZipFile, skill_root: Path, theme: str) -> None:
    media_digests = {
        sha256_bytes(archive.read(name))
        for name in archive.namelist()
        if name.startswith("ppt/media/") and not name.endswith("/")
    }
    required = [
        "assets/brand/stevens-identifier-negative.png",
        "assets/brand/stevens-star-gold.png",
        "assets/brand/campus-view.png",
    ]
    if theme == "white":
        required.append("assets/brand/stevens-identifier-positive.png")
    for relative in required:
        digest = sha256_file(skill_root / relative)
        if digest not in media_digests:
            raise ValidationError(f"{theme} deck does not contain the unchanged asset {relative}")


def validate_theme_deck(
    path: Path,
    theme: str,
    manifest: dict,
    skill_root: Path,
) -> list[tuple[tuple[str, str, str], ...]]:
    with ZipFile(path) as archive:
        names = archive.namelist()
        slides = numbered_parts(names, "ppt/slides/slide")
        masters = numbered_parts(names, "ppt/slideMasters/slideMaster")
        layouts = numbered_parts(names, "ppt/slideLayouts/slideLayout")
        if len(slides) != 18:
            raise ValidationError(f"{theme} deck must have 18 slides; found {len(slides)}")
        if len(masters) < 2:
            raise ValidationError(f"{theme} deck did not preserve the source master")
        if len(layouts) < 39:
            raise ValidationError(f"{theme} deck did not preserve and extend the source layouts")

        validate_slide_size(archive)
        validate_effects_and_opacity(archive, names)
        validate_fonts(archive, names)
        validate_notes(archive, names, 18)
        validate_brand_media(archive, skill_root, theme)

        by_part = layout_names(archive, names)
        archetypes = manifest["archetypes"]
        if "Stevens — Theme Index" not in set(by_part.values()):
            raise ValidationError("theme index layout is missing")
        required = {item["layoutName"] for item in archetypes}
        validate_custom_placeholders(archive, by_part, required)
        for item in archetypes:
            actual_part = slide_layout_part(archive, item["slideNumber"])
            actual_name = by_part.get(actual_part)
            if actual_name != item["layoutName"]:
                raise ValidationError(
                    f"{theme} slide {item['slideNumber']} uses {actual_name!r}, "
                    f"expected {item['layoutName']!r}"
                )

        if theme == "dark":
            validate_text_color_rule(archive, names, "A32638")
        validate_footer_alignment(archive, names)

        return [geometry_signature(parse_xml(archive, name)) for name in slides]


def validate_gallery(path: Path) -> None:
    with ZipFile(path) as archive:
        names = archive.namelist()
        slides = numbered_parts(names, "ppt/slides/slide")
        masters = numbered_parts(names, "ppt/slideMasters/slideMaster")
        layouts = numbered_parts(names, "ppt/slideLayouts/slideLayout")
        if len(slides) != 4 or len(masters) < 2 or len(layouts) < 22:
            raise ValidationError(
                f"gallery structure mismatch: slides={len(slides)}, masters={len(masters)}, layouts={len(layouts)}"
            )
        validate_slide_size(archive)
        validate_effects_and_opacity(archive, names)
        validate_fonts(archive, names)
        validate_notes(archive, names, 4)
        validate_footer_alignment(archive, names)
        if "Stevens — Gallery Canvas" not in set(layout_names(archive, names).values()):
            raise ValidationError("gallery canvas layout is missing")


def validate_manifest(manifest: dict) -> None:
    if manifest.get("version") != "2.0.0":
        raise ValidationError("unexpected template manifest version")
    if manifest.get("defaultTheme") != "white":
        raise ValidationError("White must remain the default theme")
    if set(manifest.get("themes", {})) != set(THEME_FILES):
        raise ValidationError("manifest themes must be exactly white and dark")
    if manifest.get("templateStructure") != {
        "theme": {"slides": 18, "masters": 2, "layouts": 39, "notesSlides": 18, "indexSlide": 1},
        "gallery": {"slides": 4, "masters": 2, "layouts": 22, "notesSlides": 4},
    }:
        raise ValidationError("unexpected template structure contract")
    archetypes = manifest.get("archetypes", [])
    if len(archetypes) != 17:
        raise ValidationError("manifest must define exactly 17 archetypes")
    if [item.get("slideNumber") for item in archetypes] != list(range(2, 19)):
        raise ValidationError("archetype slide numbers must be 2 through 18")
    if len({item.get("id") for item in archetypes}) != 17:
        raise ValidationError("archetype ids must be unique")


def validate_no_unit_lockup(plugin_root: Path) -> None:
    forbidden = b"intelli" + b"sys"
    for path in plugin_root.rglob("*"):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.name.endswith((".pyc", ".inspect.ndjson"))
        ):
            continue
        if forbidden in path.read_bytes().lower():
            raise ValidationError(f"unit lockup reference found in {path.relative_to(plugin_root)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Path to the stevens-slides skill root",
    )
    args = parser.parse_args()
    skill_root = args.skill_root.resolve()
    plugin_root = skill_root.parents[1]

    manifest_path = skill_root / "references/template-manifest.json"
    checksum_path = skill_root / "references/asset-checksums.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    validate_checksums(skill_root, checksum_path)
    validate_no_unit_lockup(plugin_root)

    signatures = {}
    for theme, filename in THEME_FILES.items():
        expected_asset = manifest["themes"][theme]["assetPath"]
        if PurePosixPath(expected_asset).name != filename:
            raise ValidationError(f"manifest asset path mismatch for {theme}")
        signatures[theme] = validate_theme_deck(
            skill_root / expected_asset,
            theme,
            manifest,
            skill_root,
        )
    if signatures["white"] != signatures["dark"]:
        raise ValidationError("theme slide geometry differs across White and Dark")

    validate_gallery(skill_root / manifest["galleryAsset"])
    print("Stevens presentation templates: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValidationError, KeyError, ValueError, ET.ParseError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
