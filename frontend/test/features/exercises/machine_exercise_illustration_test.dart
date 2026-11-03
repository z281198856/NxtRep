import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/features/exercises/domain/exercise_models.dart';
import 'package:nxtrep/features/exercises/presentation/widgets/anatomy_motion_illustration.dart';

void main() {
  test(
    'machine variants select the correct joint instead of a generic pose',
    () {
      final examples = <(String, String?), ExerciseMotionKind>{
        ('史密斯上斜推胸', null): ExerciseMotionKind.benchPress,
        ('史密斯坐姿推肩', 'vertical_push'): ExerciseMotionKind.verticalPush,
        ('史密斯保加利亚分腿蹲', 'lunge'): ExerciseMotionKind.lunge,
        ('反向蝴蝶机飞鸟', 'reverse_fly'): ExerciseMotionKind.reverseFly,
        ('上斜推胸机', 'horizontal_push'): ExerciseMotionKind.horizontalPush,
        ('腿举机', 'leg_press'): ExerciseMotionKind.legPress,
        ('坐姿腿屈伸', 'knee_extension'): ExerciseMotionKind.kneeExtension,
        ('坐姿腿弯举', 'seated_leg_curl'): ExerciseMotionKind.seatedLegCurl,
        ('俯卧腿弯举', 'lying_leg_curl'): ExerciseMotionKind.lyingLegCurl,
        ('坐姿髋外展', 'seated_hip_abduction'):
            ExerciseMotionKind.seatedHipAbduction,
        ('坐姿髋内收', 'seated_hip_adduction'):
            ExerciseMotionKind.seatedHipAdduction,
        ('史密斯站姿提踵', 'calf_raise'): ExerciseMotionKind.calfRaise,
        ('坐姿提踵机', 'seated_calf_raise'): ExerciseMotionKind.seatedCalfRaise,
        ('臀推机', 'hip_thrust'): ExerciseMotionKind.hipThrust,
        ('器械卷腹', 'seated_crunch'): ExerciseMotionKind.seatedCrunch,
      };
      for (final MapEntry(key: (name, pattern), value: expected)
          in examples.entries) {
        expect(exerciseMotionKind(name, pattern), expected, reason: name);
      }
      expect(equipmentLabel('smith_machine'), '史密斯机');
    },
  );

  test(
    'leg extension, curl and hip guides move in distinct working directions',
    () {
      final extension = anatomyLowerBodyMotionPath(
        ExerciseMotionKind.kneeExtension,
      );
      final curl = anatomyLowerBodyMotionPath(ExerciseMotionKind.seatedLegCurl);
      expect(extension.end.dx, greaterThan(extension.start.dx));
      expect(extension.end.dy, lessThan(extension.start.dy));
      expect(curl.end.dx, lessThan(curl.start.dx));
      expect(curl.end.dy, greaterThan(curl.start.dy));
      final abduct = anatomyLowerBodyMotionPath(
        ExerciseMotionKind.seatedHipAbduction,
      );
      final adduct = anatomyLowerBodyMotionPath(
        ExerciseMotionKind.seatedHipAdduction,
      );
      expect(abduct.end.dx, greaterThan(abduct.start.dx));
      expect(adduct.end.dx, lessThan(adduct.start.dx));
      final lying = anatomyLowerBodyMotionPath(ExerciseMotionKind.lyingLegCurl);
      expect(lying.end.dy, lessThan(lying.start.dy));
      final press = anatomyLowerBodyMotionPath(ExerciseMotionKind.legPress);
      expect(press.end.dx, greaterThan(press.start.dx));
      expect(press.end.dy, lessThan(press.start.dy));
    },
  );

  testWidgets(
    'new machine motions render anatomy and can pause without errors',
    (tester) async {
      final examples = <(String, String, String, List<String>)>[
        ('史密斯上斜推胸', 'horizontal_push', 'smith_machine', ['chest']),
        ('史密斯坐姿推肩', 'vertical_push', 'smith_machine', ['shoulders']),
        ('腿举机', 'leg_press', 'machine', ['quadriceps', 'gluteus']),
        ('坐姿腿屈伸', 'knee_extension', 'machine', ['quadriceps']),
        ('坐姿腿弯举', 'seated_leg_curl', 'machine', ['hamstrings']),
        ('俯卧腿弯举', 'lying_leg_curl', 'machine', ['hamstrings']),
        ('坐姿髋外展', 'seated_hip_abduction', 'machine', ['gluteus']),
        ('坐姿髋内收', 'seated_hip_adduction', 'machine', ['adductors']),
        ('坐姿提踵机', 'seated_calf_raise', 'machine', ['calves']),
        ('史密斯站姿提踵', 'calf_raise', 'smith_machine', ['calves']),
        ('臀推机', 'hip_thrust', 'machine', ['gluteus']),
        ('器械卷腹', 'seated_crunch', 'machine', ['core']),
      ];
      for (final (name, pattern, equipment, muscles) in examples) {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(
                child: AnatomyMotionIllustration(
                  key: ValueKey(name),
                  name: name,
                  movementPattern: pattern,
                  equipment: equipment,
                  primaryMuscles: muscles,
                  secondaryMuscles: const [],
                ),
              ),
            ),
          ),
        );
        await tester.pump(const Duration(milliseconds: 700));
        expect(
          find.text('主练：${muscles.map(muscleLabel).join('、')}'),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull, reason: name);
        await tester.tap(find.byIcon(Icons.pause_rounded));
        await tester.pump();
        expect(find.byIcon(Icons.play_arrow_rounded), findsOneWidget);
      }
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
