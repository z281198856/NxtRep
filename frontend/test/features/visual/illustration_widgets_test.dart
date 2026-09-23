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
      ExerciseMotionKind.seatedRow,
    );
    expect(
      exerciseMotionKind('哑铃推举', 'vertical_push'),
      ExerciseMotionKind.verticalPush,
    );
    expect(exerciseMotionKind('平板支撑', 'core'), ExerciseMotionKind.plank);
    expect(
      exerciseMotionKind('哑铃侧平举', 'shoulder_abduction'),
      ExerciseMotionKind.lateralRaise,
    );
    expect(exerciseMotionKind('肩部飞鸟', null), ExerciseMotionKind.lateralRaise);
    expect(exerciseMotionKind('站姿哑铃飞鸟', null), ExerciseMotionKind.lateralRaise);
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

  test('maps high-risk catalog exercises to dedicated motion families', () {
    final expected = <(String, String), ExerciseMotionKind>{
      ('哑铃平板卧推', 'horizontal_push'): ExerciseMotionKind.benchPress,
      ('单臂哑铃划船', 'horizontal_pull'): ExerciseMotionKind.singleArmRow,
      ('绳索坐姿划船', 'horizontal_pull'): ExerciseMotionKind.seatedRow,
      ('绳索面拉', 'horizontal_pull'): ExerciseMotionKind.facePull,
      ('绳索直臂下压', 'vertical_pull'): ExerciseMotionKind.straightArmPulldown,
      ('引体向上', 'vertical_pull'): ExerciseMotionKind.pullUp,
      ('绳索过顶臂屈伸', 'elbow_extension'): ExerciseMotionKind.overheadExtension,
      ('绳索侧平举', 'shoulder_abduction'): ExerciseMotionKind.singleArmLateralRaise,
      ('绳索上斜夹胸', 'chest_fly'): ExerciseMotionKind.lowToHighFly,
      ('标准俯卧撑', 'horizontal_push'): ExerciseMotionKind.pushUp,
      ('平板支撑', 'core'): ExerciseMotionKind.plank,
      ('臀桥', 'hip_extension'): ExerciseMotionKind.gluteBridge,
      ('跪姿绳索卷腹', 'core'): ExerciseMotionKind.kneelingCrunch,
    };

    for (final MapEntry(key: (name, pattern), value: kind)
        in expected.entries) {
      expect(exerciseMotionKind(name, pattern), kind, reason: name);
    }
  });

  test('fly motion guides point in the anatomical working direction', () {
    final lateralRaise = anatomyLateralRaiseMotionPath();
    expect(lateralRaise.leftEnd.dx, lessThan(lateralRaise.leftStart.dx));
    expect(lateralRaise.leftEnd.dy, lessThan(lateralRaise.leftStart.dy));
    expect(lateralRaise.rightEnd.dx, greaterThan(lateralRaise.rightStart.dx));
    expect(lateralRaise.rightEnd.dy, lessThan(lateralRaise.rightStart.dy));

    final chestFly = anatomyFlyMotionPath(ExerciseMotionKind.chestFly);
    expect(chestFly.leftEnd.dx, greaterThan(chestFly.leftStart.dx));
    expect(chestFly.rightEnd.dx, lessThan(chestFly.rightStart.dx));

    final reverseFly = anatomyFlyMotionPath(ExerciseMotionKind.reverseFly);
    expect(reverseFly.leftEnd.dx, lessThan(reverseFly.leftStart.dx));
    expect(reverseFly.rightEnd.dx, greaterThan(reverseFly.rightStart.dx));
  });

  test('dedicated cable motion guides follow their working directions', () {
    final facePull = anatomyBilateralMotionPath(ExerciseMotionKind.facePull);
    expect(facePull.leftEnd.dx, lessThan(facePull.leftStart.dx));
    expect(facePull.rightEnd.dx, greaterThan(facePull.rightStart.dx));

    final singleArmRow = anatomyBilateralMotionPath(
      ExerciseMotionKind.singleArmRow,
    );
    expect(singleArmRow.leftEnd, singleArmRow.leftStart);
    expect(singleArmRow.rightEnd.dy, lessThan(singleArmRow.rightStart.dy));

    final pulldown = anatomyBilateralMotionPath(
      ExerciseMotionKind.straightArmPulldown,
    );
    expect(pulldown.leftEnd.dy, greaterThan(pulldown.leftStart.dy));
    expect(pulldown.rightEnd.dy, greaterThan(pulldown.rightStart.dy));

    final overhead = anatomyBilateralMotionPath(
      ExerciseMotionKind.overheadExtension,
    );
    expect(overhead.leftEnd.dy, lessThan(overhead.leftStart.dy));
    expect(overhead.rightEnd.dy, lessThan(overhead.rightStart.dy));

    final lowToHigh = anatomyBilateralMotionPath(
      ExerciseMotionKind.lowToHighFly,
    );
    expect(lowToHigh.leftEnd.dx, greaterThan(lowToHigh.leftStart.dx));
    expect(lowToHigh.leftEnd.dy, lessThan(lowToHigh.leftStart.dy));
    expect(lowToHigh.rightEnd.dx, lessThan(lowToHigh.rightStart.dx));
    expect(lowToHigh.rightEnd.dy, lessThan(lowToHigh.rightStart.dy));
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

  testWidgets('lateral raise clearly starts beside thighs and moves outward', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: AnatomyMotionIllustration(
            name: '哑铃侧平举',
            movementPattern: 'shoulder_abduction',
            equipment: 'dumbbell',
            primaryMuscles: ['shoulders'],
            secondaryMuscles: ['trapezius'],
          ),
        ),
      ),
    );

    expect(find.text('双手从大腿两侧向外抬至肩高'), findsOneWidget);
    expect(find.text('箭头从腿侧向外上方'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('bodyweight motions use exercise-specific side-view guidance', (
    tester,
  ) async {
    Future<void> pumpMotion(String name, String pattern) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light(),
          home: Scaffold(
            body: AnatomyMotionIllustration(
              name: name,
              movementPattern: pattern,
              equipment: 'bodyweight',
              primaryMuscles: const ['core'],
              secondaryMuscles: const ['shoulders'],
            ),
          ),
        ),
      );
    }

    await pumpMotion('标准俯卧撑', 'horizontal_push');
    expect(find.text('侧视：身体保持直线并推离地面'), findsOneWidget);
    expect(find.text('箭头指向推起方向'), findsOneWidget);

    await pumpMotion('平板支撑', 'core');
    expect(find.text('侧视：持续收紧核心，避免塌腰或抬髋'), findsOneWidget);
    expect(find.text('绿线检查身体是否平直'), findsOneWidget);

    await pumpMotion('臀桥', 'hip_extension');
    expect(find.text('侧视：脚掌踩稳，夹臀将髋部抬起'), findsOneWidget);
    expect(find.text('箭头指向抬髋方向'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });
}
