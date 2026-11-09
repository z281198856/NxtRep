"""Export the existing Flutter motion equations; no guessed replacement movement data.

Run from the repository root. Requires the Dart SDK already used by Flutter.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "frontend/lib/features/exercises/presentation/widgets/anatomy_motion_illustration.dart"
DESTINATION = ROOT / "ios-native/NxtRepNative/FlutterMotionData.json"


def main():
    text = SOURCE.read_text(encoding="utf-8")
    enum = text[text.index("enum ExerciseMotionKind"):text.index("ExerciseMotionKind exerciseMotionKind")]
    equations = text[text.index("class _Pose {"):]
    classifier = text[text.index("ExerciseMotionKind exerciseMotionKind"):text.index("double anatomyMotionProgress")]
    rules = []
    for condition, kind in re.findall(r"if\s*\((.*?)\)\s*\{?\s*return ExerciseMotionKind\.(\w+);", classifier, re.S):
        groups = []
        for alternative in condition.split("||"):
            groups.append([re.findall(r"'([^']+)'", m) for m in re.findall(r"has\(const\s*\[(.*?)\]\)", alternative, re.S)])
        if groups and all(groups):
            rules.append({"kind": kind, "groups": groups})
    stub = r"""
import 'dart:convert';
double? lerpDouble(num a, num b, double t) => a + (b-a)*t;
class Offset {
  const Offset(this.dx, this.dy);
  final double dx, dy;
  Offset translate(double x, double y) => Offset(dx+x,dy+y);
  static Offset? lerp(Offset a, Offset b, double t) => Offset(a.dx+(b.dx-a.dx)*t,a.dy+(b.dy-a.dy)*t);
}
"""
    exporter = r"""
List<double> point(Offset p) => [double.parse(p.dx.toStringAsFixed(5)),double.parse(p.dy.toStringAsFixed(5))];
Map<String,dynamic> encodePose(_Pose p) => {
  'head':point(p.head),'neck':point(p.neck),
  'leftShoulder':point(p.leftShoulder),'rightShoulder':point(p.rightShoulder),
  'leftElbow':point(p.leftElbow),'rightElbow':point(p.rightElbow),
  'leftHand':point(p.leftHand),'rightHand':point(p.rightHand),
  'leftHip':point(p.leftHip),'rightHip':point(p.rightHip),
  'leftKnee':point(p.leftKnee),'rightKnee':point(p.rightKnee),
  'leftAnkle':point(p.leftAnkle),'rightAnkle':point(p.rightAnkle),
};
void main() {
  final result = <String,dynamic>{};
  for (final kind in ExerciseMotionKind.values) {
    result[kind.name] = {
      'direction':_directionLabel(kind),
      'stageStart':_stageLabel(kind,0),'stageEnd':_stageLabel(kind,1),
      'caption':_motionCaption(kind,'bodyweight',''),
      'poses': {
        for (final equipment in ['bodyweight','machine']) equipment:
          [for (int frame=0; frame<=30; frame++) encodePose(_displayPose(kind,frame/30,equipment))]
      }
    };
  }
  print(jsonEncode(result));
}
"""
    dart = shutil.which("dart")
    if not dart:
        raise SystemExit("Dart SDK is required")
    if dart.lower().endswith(".bat"):
        binary = Path(dart).parent / "cache/dart-sdk/bin/dart.exe"
        if binary.exists():
            dart = str(binary)
    with tempfile.TemporaryDirectory(prefix="nxtrep-motion-") as directory:
        program = Path(directory) / "export.dart"
        program.write_text(stub + enum + equations + exporter, encoding="utf-8")
        result = subprocess.run([dart, str(program)], capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            raise SystemExit(result.stderr)
        motions = json.loads(result.stdout)
    for motion in motions.values():
        for frames in motion["poses"].values():
            assert len(frames) == 31
            assert all(len(frame) == 14 for frame in frames)
    data = {"source_sha256": hashlib.sha256(text.encode()).hexdigest(), "rules": rules, "motions": motions}
    DESTINATION.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Exported {len(motions)} original motion kinds, {len(rules)} ordered classification rules, {DESTINATION.stat().st_size} bytes")


if __name__ == "__main__":
    main()
