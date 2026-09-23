import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/core/theme/app_theme.dart';
import 'package:nxtrep/features/exercises/presentation/widgets/anatomy_motion_illustration.dart';
import 'package:nxtrep/features/nutrition/presentation/widgets/food_line_art.dart';

void main() {
  test('classifies common foods into stable line-art categories', () {
    expect(foodVisualCategory('鸡胸肉'), FoodVisualCategory.protein);
    expect(foodVisualCategory('燕麦饭'), FoodVisualCategory.grain);
    expect(foodVisualCategory('西兰花'), FoodVisualCategory.vegetable);
    expect(foodVisualCategory('苹果'), FoodVisualCategory.fruit);
    expect(foodVisualCategory('低脂牛奶'), FoodVisualCategory.dairy);
    expect(foodVisualCategory('黑咖啡'), FoodVisualCategory.beverage);
    expect(foodVisualCategory('巧克力饼干'), FoodVisualCategory.snack);
    expect(foodVisualCategory('家庭配方'), FoodVisualCategory.generic);
  });

  test('maps exercise names and patterns to motion families', () {
    expect(exerciseMotionKind('杠铃深蹲', 'squat'), ExerciseMotionKind.squat);
    expect(exerciseMotionKind('罗马尼亚硬拉', 'hinge'), ExerciseMotionKind.hinge);
    expect(
      exerciseMotionKind('坐姿划船', 'horizontal_pull'),
      ExerciseMotionKind.horizontalPull,
    );
    expect(
      exerciseMotionKind('哑铃推举', 'vertical_push'),
      ExerciseMotionKind.verticalPush,
    );
    expect(exerciseMotionKind('平板支撑', 'core'), ExerciseMotionKind.core);
    expect(
      exerciseMotionKind('哑铃侧平举', 'shoulder_abduction'),
      ExerciseMotionKind.lateralRaise,
    );
    expect(
      exerciseMotionKind('绳索夹胸', 'chest_fly'),
      ExerciseMotionKind.chestFly,
    );
    expect(
      exerciseMotionKind('哑铃飞鸟', 'chest_fly'),
      ExerciseMotionKind.chestFly,
    );
    expect(
      exerciseMotionKind('哑铃反向飞鸟', 'horizontal_pull'),
      ExerciseMotionKind.reverseFly,
    );
    expect(
      exerciseMotionKind('俯身后束飞鸟', 'horizontal_pull'),
      ExerciseMotionKind.reverseFly,
    );
    expect(
      exerciseMotionKind('绳索三头下压', 'elbow_extension'),
      ExerciseMotionKind.elbowExtension,
    );
    expect(
      exerciseMotionKind('绳索臀部后踢', 'hip_extension'),
      ExerciseMotionKind.hipExtension,
    );
  });

  test('fly motion guides point in the anatomical working direction', () {
    final chestFly = anatomyFlyMotionPath(ExerciseMotionKind.chestFly);
    expect(chestFly.leftEnd.dx, greaterThan(chestFly.leftStart.dx));
    expect(chestFly.rightEnd.dx, lessThan(chestFly.rightStart.dx));

    final reverseFly = anatomyFlyMotionPath(ExerciseMotionKind.reverseFly);
    expect(reverseFly.leftEnd.dx, lessThan(reverseFly.leftStart.dx));
    expect(reverseFly.rightEnd.dx, greaterThan(reverseFly.rightStart.dx));
  });

  test('motion cycle only presents the forward working phase', () {
    expect(anatomyMotionProgress(0.05), 0);
    expect(anatomyMotionProgress(0.45), inExclusiveRange(0, 1));
    expect(anatomyMotionProgress(0.90), 1);
  });

  testWidgets('food line art exposes an accessible image description', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(body: FoodLineArt(name: '鸡胸肉')),
      ),
    );

    expect(find.bySemanticsLabel('鸡胸肉 线描食品插图'), findsOneWidget);
    expect(find.byType(CustomPaint), findsWidgets);
    semantics.dispose();
  });

  testWidgets('anatomy illustration animates and can be paused', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: SingleChildScrollView(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: AnatomyMotionIllustration(
                name: '杠铃深蹲',
                movementPattern: 'squat',
                equipment: 'barbell',
                primaryMuscles: ['quadriceps', 'gluteus'],
                secondaryMuscles: ['core'],
              ),
            ),
          ),
        ),
      ),
    );

    expect(find.text('动态解剖示意'), findsOneWidget);
    expect(find.text('主要发力'), findsOneWidget);
    expect(find.text('主练：股四头肌、臀肌'), findsOneWidget);
    expect(find.text('绿色箭头看方向'), findsOneWidget);
    expect(find.byIcon(Icons.pause_rounded), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 300));

    await tester.tap(find.byIcon(Icons.pause_rounded));
    await tester.pump();
    expect(find.byIcon(Icons.play_arrow_rounded), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('dumbbell fly clearly labels inward and outward directions', (
    tester,
  ) async {
    Future<void> pumpFly(String name, String movementPattern) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light(),
          home: Scaffold(
            body: AnatomyMotionIllustration(
              name: name,
              movementPattern: movementPattern,
              equipment: 'dumbbell',
              primaryMuscles: const ['chest'],
              secondaryMuscles: const ['shoulders'],
            ),
          ),
        ),
      );
    }

    await pumpFly('哑铃飞鸟', 'chest_fly');
    expect(find.text('俯视：双臂从两侧向胸部上方夹合'), findsOneWidget);
    expect(find.text('箭头向内夹合'), findsOneWidget);

    await pumpFly('哑铃反向飞鸟', 'horizontal_pull');
    expect(find.text('双臂从胸前向两侧打开，后束发力'), findsOneWidget);
    expect(find.text('箭头向外打开'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });
}
