"""Keep the checked-in Xcode group, sources and small bundled JSON resources in sync."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "NxtRepNative.xcodeproj/project.pbxproj"


def identifier(kind, name):
    return hashlib.sha256(("nxtrep-native:" + kind + ":" + name).encode()).hexdigest()[:24].upper()


def main():
    text = PROJECT.read_text(encoding="utf-8")
    for file in sorted((ROOT / "NxtRepNative").iterdir()):
        if file.suffix not in {".swift", ".json"}:
            continue
        name = file.name
        if f"path = {name};" in text:
            continue
        reference, build = identifier("ref", name), identifier("build", name)
        phase = "Sources" if file.suffix == ".swift" else "Resources"
        filetype = "sourcecode.swift" if file.suffix == ".swift" else "text.json"
        text = text.replace("/* End PBXFileReference section */", f'\t\t{reference} /* {name} */ = {{isa = PBXFileReference; lastKnownFileType = {filetype}; path = {name}; sourceTree = "<group>"; }};\n/* End PBXFileReference section */')
        text = text.replace("/* End PBXBuildFile section */", f"\t\t{build} /* {name} in {phase} */ = {{isa = PBXBuildFile; fileRef = {reference} /* {name} */; }};\n/* End PBXBuildFile section */")
        anchor = "\t\t\t\tF4E461FD2BFB000200000008 /* Assets.xcassets */,"
        text = text.replace(anchor, anchor + f"\n\t\t\t\t{reference} /* {name} */,")
        anchor = "\t\t\t\tF4E461FD2BFB000100000001 /* NxtRepNativeApp.swift in Sources */," if phase == "Sources" else "\t\t\t\tF4E461FD2BFB000100000007 /* Assets.xcassets in Resources */,"
        if anchor not in text:
            raise SystemExit(f"Missing {phase} insertion point")
        text = text.replace(anchor, anchor + f"\n\t\t\t\t{build} /* {name} in {phase} */,")
        print("Added", name)
    PROJECT.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
