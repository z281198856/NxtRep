import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:nxtrep/core/theme/app_theme.dart';
import 'package:nxtrep/features/nutrition/data/nutrition_repository.dart';
import 'package:nxtrep/features/nutrition/domain/nutrition_date.dart';
import 'package:nxtrep/features/nutrition/domain/nutrition_models.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_controller.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_page.dart';

import 'nutrition_quick_entries_test.dart' as helpers;

Map<String, Object> meal() => {
  'id': 'saved-meal',
  'version': 3,
  'meal_type': 'dinner',
  'eaten_at': '2024-02-28T10:00:00Z',
  'items': [
    {'name': '鸡肉饭', 'amount_g': 250},
  ],
  'totals': {'kcal': 500, 'protein_g': 30, 'carbs_g': 60, 'fat_g': 15},
};

void main() {
  test(
    'backfill keeps Shanghai calendar date around year and leap-day boundaries',
    () {
      final now = DateTime.parse('2026-01-01T00:30:00+08:00');
      expect(nutritionToday(now: now), DateTime(2026, 1, 1));
      for (final day in [DateTime(2024, 2, 29), DateTime(2025, 12, 31)]) {
        for (final meal in ['breakfast', 'lunch', 'dinner', 'water']) {
          final china = nutritionRecordedAt(
            day,
            meal,
            now: now,
          ).add(const Duration(hours: 8));
          expect(
            [china.year, china.month, china.day],
            [day.year, day.month, day.day],
          );
        }
      }
      expect(
        nutritionRecordedAt(DateTime(2026, 1, 1), 'water', now: now),
        now.toUtc(),
      );
    },
  );

  testWidgets(
    'target ranges and distinct main-meal coverage fit a narrow screen',
    (tester) async {
      tester.view.physicalSize = const Size(360, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = helpers.makeApi((request) async {
        if (request.url.path.endsWith('/daily-summary')) {
          return helpers.json({
            'date': '2024-02-29',
            'consumed': meal()['totals'],
            'record_completeness': .33,
            'recorded_meals': ['breakfast'],
            'target': {
              'kcal_min': '1800',
              'kcal_max': '2100',
              'protein_min_g': '100',
              'protein_max_g': '130',
              'carbs_min_g': '200',
              'carbs_max_g': '260',
              'fat_min_g': '50',
              'fat_max_g': '65',
            },
          });
        }
        return helpers.nutritionResponse(request);
      });
      final controller = NutritionController(NutritionRepository(api));
      addTearDown(api.close);
      addTearDown(controller.dispose);
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light(),
          home: NutritionPage(controller: controller),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('1800–2100 千卡'), findsOneWidget);
      for (final range in ['100–130 g', '200–260 g', '50–65 g']) {
        expect(find.text(range), findsOneWidget);
      }
      expect(find.text('三餐已记 1/3'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('past water loads selected day and saving stays on that day', (
    tester,
  ) async {
    final requests = <http.Request>[];
    final api = helpers.makeApi((request) async {
      requests.add(request);
      if (request.url.path.endsWith('/water')) {
        if (request.method == 'GET') {
          return helpers.json([
            {
              'id': 'water',
              'amount_ml': 200,
              'consumed_at': '2024-02-29T04:00:00Z',
            },
          ]);
        }
        return helpers.json({'id': 'new-water'}, 201);
      }
      return helpers.nutritionResponse(request);
    });
    final controller = NutritionController(NutritionRepository(api));
    addTearDown(api.close);
    addTearDown(controller.dispose);
    await controller.selectDate(DateTime(2024, 2, 29));
    await tester.pumpWidget(
      MaterialApp(home: NutritionPage(controller: controller)),
    );
    await tester.pumpAndSettle();
    expect(find.text('补记食品'), findsOneWidget);
    await tester.tap(find.text('记饮水'));
    await tester.pumpAndSettle();
    expect(find.text('记录至 2024年2月29日'), findsOneWidget);
    expect(find.text('当天已喝 200 ml'), findsOneWidget);
    await tester.tap(find.text('保存饮水'));
    await tester.pumpAndSettle();
    final post = requests.singleWhere((r) => r.method == 'POST');
    final data = jsonDecode(post.body) as Map<String, dynamic>;
    expect(
      DateTime.parse(data['consumed_at']).add(const Duration(hours: 8)).day,
      29,
    );
    expect(
      requests
          .where((r) => r.method == 'GET' && r.url.path.endsWith('/water'))
          .every((r) => r.url.queryParameters['date'] == '2024-02-29'),
      isTrue,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('copy previews food and date, handles failure, then saves once', (
    tester,
  ) async {
    final posts = <http.Request>[];
    var fail = true;
    final api = helpers.makeApi((request) async {
      if (request.url.path.endsWith('/entries/recent')) {
        return helpers.json([meal()]);
      }
      if (request.method == 'POST') {
        posts.add(request);
        return fail
            ? helpers.json({
                'error': {'code': 'CONFLICT', 'message': '原餐食已更新，请重新选择'},
              }, 409)
            : helpers.json(meal(), 201);
      }
      return helpers.nutritionResponse(request);
    });
    final controller = NutritionController(NutritionRepository(api));
    addTearDown(api.close);
    addTearDown(controller.dispose);
    await controller.selectDate(DateTime(2024, 2, 29));
    await tester.pumpWidget(
      MaterialApp(home: NutritionPage(controller: controller)),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('复制上一餐'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('鸡肉饭'));
    await tester.pumpAndSettle();
    expect(posts, isEmpty);
    expect(find.text('记录至 2024年2月29日'), findsOneWidget);
    expect(find.text('250 g'), findsOneWidget);
    await tester.tap(find.text('确认复制'));
    await tester.pumpAndSettle();
    expect(find.text('原餐食已更新，请重新选择'), findsWidgets);
    fail = false;
    await tester.tap(find.text('确认复制'));
    await tester.pumpAndSettle();
    expect(posts, hasLength(2));
    expect(posts.last.url.path, endsWith('/entries/saved-meal/copy'));
    final payload = jsonDecode(posts.last.body) as Map<String, dynamic>;
    expect(payload['expected_version'], 3);
    expect(payload['meal_type'], 'dinner');
    expect(payload['eaten_at'], '2024-02-29T10:00:00.000Z');
    expect(find.text('确认复制餐食'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  test(
    'manual and catalog entries retain explicitly chosen date after navigation',
    () async {
      final writes = <Map<String, dynamic>>[];
      final api = helpers.makeApi((request) async {
        if (request.method == 'POST') {
          final data = jsonDecode(request.body) as Map<String, dynamic>;
          writes.add(data);
          return helpers.json({...meal(), 'eaten_at': data['eaten_at']}, 201);
        }
        return helpers.nutritionResponse(request);
      });
      final controller = NutritionController(NutritionRepository(api));
      addTearDown(api.close);
      addTearDown(controller.dispose);
      final captured = DateTime(2024, 2, 29);
      await controller.selectDate(DateTime(2024, 3, 1));
      await controller.add(
        const ManualNutritionInput(
          name: '测试',
          mealType: 'breakfast',
          amountG: 100,
          kcal: 100,
          proteinG: 5,
          carbsG: 10,
          fatG: 3,
        ),
        date: captured,
      );
      final food = FoodItem.fromJson({
        'id': 'food',
        'food_version_id': 'v1',
        'name': '测试',
        'basis_amount_g': 100,
        'kcal': 100,
        'protein_g': 5,
        'carbs_g': 10,
        'fat_g': 3,
      });
      await controller.addFood(
        FoodServingInput(food: food, amountG: 100, mealType: 'dinner'),
        date: captured,
      );
      expect(writes.map((d) => d['eaten_at']), [
        '2024-02-29T00:00:00.000Z',
        '2024-02-29T10:00:00.000Z',
      ]);
      expect(controller.selectedDate, DateTime(2024, 3, 1));
    },
  );
}
