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
    expect(find.byIcon(Icons.pause_rounded), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 300));

    await tester.tap(find.byIcon(Icons.pause_rounded));
    await tester.pump();
    expect(find.byIcon(Icons.play_arrow_rounded), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });
}
