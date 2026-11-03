import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/theme/app_theme.dart';
import 'package:nxtrep/features/nutrition/data/nutrition_repository.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_controller.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_page.dart';
import 'package:nxtrep/features/progress/data/body_repository.dart';
import 'package:nxtrep/features/progress/presentation/progress_controller.dart';
import 'package:nxtrep/features/progress/presentation/progress_page.dart';

http.Response json(Object value, [int status = 200]) => http.Response.bytes(
  utf8.encode(jsonEncode(value)),
  status,
  headers: {'content-type': 'application/json'},
);
const totals = {'kcal': 0, 'protein_g': 0, 'carbs_g': 0, 'fat_g': 0};

void main() {
  for (final meal in ['早餐', '午餐', '晚餐']) {
    testWidgets('$meal shortcut opens food picker and retains meal type', (
      tester,
    ) async {
      final api = makeApi((request) async => nutritionResponse(request));
      final controller = NutritionController(NutritionRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      await tester.pumpWidget(
        MaterialApp(home: NutritionPage(controller: controller)),
      );
      await tester.pumpAndSettle();
      final row = find.byKey(const ValueKey('nutrition-quick-entries'));
      expect(
        tester.getTopLeft(row).dy,
        greaterThan(tester.getBottomLeft(find.text('蛋白质')).dy),
      );
      expect(
        tester.getBottomLeft(row).dy,
        lessThan(tester.getTopLeft(find.text('今日记录')).dy),
      );
      for (final label in ['早餐', '午餐', '晚餐', '记饮水']) {
        expect(
          find.descendant(of: row, matching: find.text(label)).hitTestable(),
          findsOneWidget,
        );
      }
      await tester.tap(find.text(meal));
      await tester.pumpAndSettle();
      await tester.tap(find.text('测试米饭'));
      await tester.pumpAndSettle();
      final dropdown = tester.widget<DropdownButtonFormField<String>>(
        find.byType(DropdownButtonFormField<String>),
      );
      expect(
        dropdown.initialValue,
        {'早餐': 'breakfast', '午餐': 'lunch', '晚餐': 'dinner'}[meal],
      );
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
    'water validates, saves, reloads totals and deletes; errors stay visible',
    (tester) async {
      tester.view.physicalSize = const Size(360, 900);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final water = <Map<String, Object>>[];
      var failSave = false;
      final api = makeApi((request) async {
        if (request.url.path.endsWith('/nutrition/water')) {
          if (request.method == 'GET') return json(water);
          if (failSave) {
            return json({
              'error': {'code': 'UNAVAILABLE', 'message': '暂时无法保存饮水'},
            }, 503);
          }
          expect(request.headers['Idempotency-Key'], isNotEmpty);
          final input = jsonDecode(request.body) as Map<String, dynamic>;
          expect(DateTime.parse(input['consumed_at'] as String).isUtc, isTrue);
          water.add({
            'id': 'water-1',
            'amount_ml': input['amount_ml'] as int,
            'consumed_at': input['consumed_at'] as String,
          });
          return json(water.last, 201);
        }
        if (request.method == 'DELETE') {
          water.clear();
          return http.Response('', 204);
        }
        return nutritionResponse(
          request,
          waterMl: water.fold(
            0,
            (sum, item) => sum + (item['amount_ml'] as int),
          ),
        );
      });
      final controller = NutritionController(NutritionRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light(),
          home: NutritionPage(controller: controller),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('记饮水'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField), '0');
      await tester.tap(find.text('保存饮水'));
      await tester.pumpAndSettle();
      expect(find.text('请输入 1–5000 ml'), findsOneWidget);
      expect(water, isEmpty);
      await tester.tap(find.text('500 ml'));
      await tester.tap(find.text('保存饮水'));
      await tester.pumpAndSettle();
      expect(find.text('当天已喝 500 ml'), findsOneWidget);
      expect(controller.summary!.waterMl, 500);
      await tester.tap(find.byTooltip('删除饮水记录'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('确认删除'));
      await tester.pumpAndSettle();
      expect(find.text('当天已喝 0 ml'), findsOneWidget);
      expect(controller.summary!.waterMl, 0);
      failSave = true;
      await tester.tap(find.text('保存饮水'));
      await tester.pumpAndSettle();
      expect(find.text('暂时无法保存饮水'), findsWidgets);
      expect(water, isEmpty);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('progress has a labelled measurement entry on a narrow screen', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = makeApi((request) async {
      final path = request.url.path;
      if (path.endsWith('/overview')) {
        return json({'training': {}, 'nutrition': {}, 'body': {}});
      }
      if (path.endsWith('/body-trend')) return json({'points': []});
      return json([]);
    });
    final controller = ProgressController(BodyRepository(api));
    addTearDown(controller.dispose);
    addTearDown(api.close);
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: ProgressPage(controller: controller, onOpenBodyProgress: () {}),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('记体重 / 体脂'));
    await tester.pumpAndSettle();
    expect(find.text('体重（kg）'), findsOneWidget);
    await tester.tap(find.text('有设备实测体脂？可选填'));
    await tester.pumpAndSettle();
    expect(find.text('设备实测体脂率（%）'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

ApiClient makeApi(Future<http.Response> Function(http.Request) handler) =>
    ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://example.test/api/v1')),
      accessTokenProvider: () => 'test',
      httpClient: MockClient(handler),
    );

http.Response nutritionResponse(http.Request request, {int waterMl = 0}) {
  final path = request.url.path;
  if (path.endsWith('/daily-summary')) {
    return json({
      'date': request.url.queryParameters['date'],
      'consumed': totals,
      'record_completeness': 0,
      'water_ml': waterMl,
    });
  }
  if (path.endsWith('/weekly-summary')) {
    return json({
      'start_date': '2026-10-19',
      'end_date': '2026-10-25',
      'daily_average': totals,
      'total_entries': 0,
      'recorded_days': 0,
      'flexible_meals': 0,
      'record_completeness': 0,
    });
  }
  if (path.endsWith('/foods/search')) {
    return json({
      'list': [
        {
          'id': 'food-1',
          'food_version_id': 'version-1',
          'name': '测试米饭',
          'basis_amount_g': 100,
          ...totals,
          'source': 'test',
          'confidence': 'confirmed',
        },
      ],
      'total': 1,
      'has_more': false,
    });
  }
  return json([]);
}
