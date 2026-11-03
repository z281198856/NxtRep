import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:image_picker/image_picker.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/media/image_upload.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/nutrition/data/nutrition_repository.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_controller.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_photo_page.dart';

void main() {
  testWidgets(
    'empty recognition keeps retry available without a zero-calorie preview',
    (tester) async {
      final bytes = base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
      );
      var estimates = 0;
      final api = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: MockClient((request) async {
          expect(request.url.path, endsWith('/entry-drafts:estimate-image'));
          estimates++;
          final zero = _totals(0, 0, 0, 0);
          return _response({
            'image_asset_id': 'test-food-image',
            'meal_type': 'lunch',
            'eaten_at': '2026-10-04T04:00:00Z',
            'recognition': {
              'foods': [],
              'assumptions': [],
              'follow_up_questions': [],
            },
            'calculation': {
              'items': [],
              'is_complete': false,
              'totals': {'minimum': zero, 'estimated': zero, 'maximum': zero},
            },
          });
        }),
      );
      final controller = NutritionController(
        NutritionRepository(api),
        imageUploader: (data) async => UploadedImage(
          assetId: 'test-food-image',
          bytes: data,
          contentType: 'image/png',
        ),
      );
      addTearDown(api.close);
      addTearDown(controller.dispose);
      await tester.pumpWidget(
        MaterialApp(
          home: NutritionPhotoPage(
            controller: controller,
            imageBytesPicker: (_) async => bytes,
          ),
        ),
      );
      await tester.tap(find.text('相册'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('识别食物并估算营养'),
        150,
        scrollable: find
            .descendant(
              of: find.byType(ListView),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('识别食物并估算营养'));
      await tester.pumpAndSettle();
      expect(find.text('照片中没有识别到食物，请换一张清晰照片'), findsOneWidget);
      expect(find.text('AI 估算预览'), findsNothing);
      expect(find.text('确认食物与营养值并保存'), findsNothing);
      expect(find.text('识别食物并估算营养'), findsOneWidget);
      await tester.tap(find.text('识别食物并估算营养'));
      await tester.pumpAndSettle();
      expect(estimates, 2);
    },
  );

  testWidgets('reviews a photo estimate, rescales portions, and saves', (
    tester,
  ) async {
    const assetId = '00000000-0000-0000-0000-000000000099';
    final png = base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    );
    final requests = <http.Request>[];
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: MockClient((request) async {
        requests.add(request);
        final path = request.url.path;
        if (path.endsWith('/entry-drafts:estimate-image')) {
          final nutrition = _totals(300, 20, 35, 10);
          return _response({
            'image_asset_id': assetId,
            'meal_type': 'lunch',
            'eaten_at': '2026-09-28T04:00:00Z',
            'recognition': {
              'foods': [],
              'assumptions': [],
              'follow_up_questions': [],
            },
            'calculation': {
              'items': [
                {
                  'match': {
                    'detected': {
                      'name': '鸡肉饭',
                      'estimated_amount_g': '250',
                      'amount_min_g': '200',
                      'amount_max_g': '300',
                      'confidence': 'medium',
                    },
                    'status': 'matched',
                  },
                  'nutrition': {
                    'minimum': nutrition,
                    'estimated': nutrition,
                    'maximum': nutrition,
                  },
                  'assumptions': [],
                  'follow_up_questions': [],
                },
              ],
              'totals': {
                'minimum': nutrition,
                'estimated': nutrition,
                'maximum': nutrition,
              },
              'is_complete': true,
            },
          });
        }
        if (path.endsWith('/nutrition/entries') && request.method == 'POST') {
          return _response({
            'id': '00000000-0000-0000-0000-000000000041',
            'meal_type': 'lunch',
            'eaten_at': '2026-09-28T04:00:00Z',
            'items': [],
            'totals': _totals(360, 24, 42, 12),
            'is_flexible_meal': false,
            'version': 1,
          });
        }
        if (path.endsWith('/nutrition/daily-summary')) {
          return _response({
            'date': '2026-09-28',
            'consumed': _totals(360, 24, 42, 12),
            'record_completeness': '0.33',
          });
        }
        if (path.endsWith('/nutrition/weekly-summary')) {
          return _response({
            'start_date': '2026-09-28',
            'end_date': '2026-10-04',
            'daily_average': _totals(360, 24, 42, 12),
            'total_entries': 1,
            'recorded_days': 1,
            'flexible_meals': 0,
            'record_completeness': '0.14',
          });
        }
        if (path.endsWith('/nutrition/entries') ||
            path.endsWith('/foods/frequent')) {
          return _response([]);
        }
        throw StateError('Unexpected request ${request.method} $path');
      }),
    );
    addTearDown(api.close);
    final controller = NutritionController(
      NutritionRepository(api),
      imageUploader: (bytes) async => UploadedImage(
        assetId: assetId,
        bytes: bytes,
        contentType: 'image/png',
      ),
    );
    addTearDown(controller.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute<void>(
                  builder: (_) => NutritionPhotoPage(
                    recordDate: DateTime(2026, 9, 28),
                    controller: controller,
                    imageBytesPicker: (source) async {
                      expect(source, ImageSource.gallery);
                      return png;
                    },
                  ),
                ),
              ),
              child: const Text('打开拍照记餐'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('打开拍照记餐'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('相册'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('识别食物并估算营养'),
      150,
      scrollable: find
          .descendant(
            of: find.byType(ListView),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('识别食物并估算营养'));
    await tester.pumpAndSettle();

    await tester.scrollUntilVisible(
      find.text('AI 估算预览'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('AI 估算预览'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.widgetWithText(TextFormField, '份量（g）'),
      250,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.enterText(find.widgetWithText(TextFormField, '份量（g）'), '300');
    await tester.scrollUntilVisible(
      find.text('确认食物与营养值并保存'),
      250,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('确认食物与营养值并保存'), findsOneWidget);
    await tester.ensureVisible(find.text('确认食物与营养值并保存'));
    await tester.tap(find.text('确认食物与营养值并保存'));
    await tester.pumpAndSettle();

    final estimate = requests.firstWhere(
      (request) => request.url.path.endsWith('/entry-drafts:estimate-image'),
    );
    final saved = requests.firstWhere(
      (request) =>
          request.method == 'POST' &&
          request.url.path.endsWith('/nutrition/entries'),
    );
    final estimateBody = jsonDecode(estimate.body) as Map<String, dynamic>;
    final saveBody = jsonDecode(saved.body) as Map<String, dynamic>;
    final item =
        (saveBody['items'] as List<dynamic>).single as Map<String, dynamic>;
    expect(estimateBody['image_asset_id'], assetId);
    expect(estimateBody['eaten_at'], '2026-09-28T04:00:00.000Z');
    expect(item['amount_g'], 300);
    expect(item['kcal'], 360);
    expect(item['source'], 'model_estimated');
    expect(find.text('打开拍照记餐'), findsOneWidget);
  });
  for (final failCorrection in [false, true]) {
    testWidgets(
      'rename reestimates without uploading or saving; failure=$failCorrection',
      (tester) async {
        tester.view.physicalSize = const Size(1000, 2400);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        var uploads = 0;
        var estimates = 0;
        final requests = <http.Request>[];
        final api = ApiClient(
          config: ApiConfig(
            baseUri: Uri.parse('https://api.example.test/api/v1'),
          ),
          accessTokenProvider: () => 'access',
          httpClient: MockClient((request) async {
            requests.add(request);
            expect(request.url.path, endsWith('/entry-drafts:estimate-image'));
            estimates++;
            if (estimates == 2 && failCorrection) {
              return http.Response.bytes(
                utf8.encode(
                  jsonEncode({
                    'error': {'code': 'AI_BUSY', 'message': '重新估算暂时不可用，请重试。'},
                  }),
                ),
                503,
                headers: {'content-type': 'application/json'},
              );
            }
            return _response(
              _qualityPhotoJson(
                estimates == 1 ? '炒鸡蛋' : '炖肉',
                estimates == 1 ? 250 : 100,
                estimates == 1 ? 300 : 180,
              ),
            );
          }),
        );
        final controller = NutritionController(
          NutritionRepository(api),
          imageUploader: (bytes) async {
            uploads++;
            return UploadedImage(
              assetId: 'food-image',
              bytes: bytes,
              contentType: 'image/png',
            );
          },
        );
        addTearDown(api.close);
        addTearDown(controller.dispose);
        await tester.pumpWidget(
          MaterialApp(
            home: NutritionPhotoPage(
              controller: controller,
              imageBytesPicker: (_) async => _testPhotoBytes(),
            ),
          ),
        );
        await tester.tap(find.text('相册'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('识别食物并估算营养'));
        await tester.pumpAndSettle();
        await tester.enterText(
          find.widgetWithText(TextFormField, '食物名称'),
          '炖肉',
        );
        await tester.enterText(
          find.widgetWithText(TextFormField, '份量（g）'),
          '100',
        );
        await tester.pump();
        expect(find.text('菜名已修改，请按修改重新估算营养后再确认。'), findsOneWidget);
        expect(
          tester
              .widget<FilledButton>(
                find.widgetWithText(FilledButton, '确认食物与营养值并保存'),
              )
              .onPressed,
          isNull,
        );
        await tester.tap(find.text('按修改重新估算营养'));
        await tester.pumpAndSettle();
        expect(uploads, 1);
        expect(estimates, 2);
        final correction =
            jsonDecode(requests.last.body) as Map<String, dynamic>;
        expect(correction['image_asset_id'], 'food-image');
        expect(correction['eaten_at'], '2026-10-16T04:00:00.000Z');
        final foods = correction['reviewed_foods'] as List<dynamic>;
        expect(foods.single['name'], '炖肉');
        expect(foods.single['estimated_amount_g'], 100);
        expect(
          tester
              .widget<TextFormField>(find.widgetWithText(TextFormField, '食物名称'))
              .controller!
              .text,
          '炖肉',
        );
        if (failCorrection) {
          expect(find.text('重新估算暂时不可用，请重试。'), findsOneWidget);
          expect(
            tester
                .widget<FilledButton>(
                  find.widgetWithText(FilledButton, '确认食物与营养值并保存'),
                )
                .onPressed,
            isNull,
          );
        } else {
          expect(find.textContaining('当前待确认估算约 180 千卡'), findsOneWidget);
          expect(
            tester
                .widget<FilledButton>(
                  find.widgetWithText(FilledButton, '确认食物与营养值并保存'),
                )
                .onPressed,
            isNotNull,
          );
        }
      },
    );
  }

  testWidgets(
    'current total follows portions and preserves manual nutrient density',
    (tester) async {
      tester.view.physicalSize = const Size(1000, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: MockClient(
          (_) async => _response(_qualityPhotoJson('熟白米饭', 250, 300)),
        ),
      );
      final controller = NutritionController(
        NutritionRepository(api),
        imageUploader: (bytes) async => UploadedImage(
          assetId: 'food-image',
          bytes: bytes,
          contentType: 'image/png',
        ),
      );
      addTearDown(api.close);
      addTearDown(controller.dispose);
      await tester.pumpWidget(
        MaterialApp(
          home: NutritionPhotoPage(
            controller: controller,
            imageBytesPicker: (_) async => _testPhotoBytes(),
          ),
        ),
      );
      await tester.tap(find.text('相册'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('识别食物并估算营养'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextFormField, '份量（g）'),
        '300',
      );
      await tester.pump();
      expect(find.textContaining('当前待确认估算约 360 千卡'), findsOneWidget);
      await tester.enterText(
        find.widgetWithText(TextFormField, '热量（千卡）'),
        '300',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, '份量（g）'),
        '100',
      );
      await tester.pump();
      expect(find.textContaining('当前待确认估算约 100 千卡'), findsOneWidget);
      expect(
        tester
            .widget<TextFormField>(find.widgetWithText(TextFormField, '蛋白质（g）'))
            .controller!
            .text,
        '8.0',
      );
    },
  );

  testWidgets('a natural portion note can reestimate without entering grams', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1000, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final requests = <http.Request>[];
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: MockClient((request) async {
        requests.add(request);
        return _response(
          _qualityPhotoJson(
            '熟白米饭',
            requests.length == 1 ? 400 : 180,
            requests.length == 1 ? 520 : 234,
          ),
        );
      }),
    );
    final controller = NutritionController(
      NutritionRepository(api),
      imageUploader: (bytes) async => UploadedImage(
        assetId: 'food-image',
        bytes: bytes,
        contentType: 'image/png',
      ),
    );
    addTearDown(api.close);
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: NutritionPhotoPage(
          controller: controller,
          imageBytesPicker: (_) async => _testPhotoBytes(),
        ),
      ),
    );
    await tester.tap(find.text('相册'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('识别食物并估算营养'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextField, '补充说明（可选）'),
      '米饭只有一小碗，请按少量重新估计',
    );
    await tester.pump();
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, '确认食物与营养值并保存'),
          )
          .onPressed,
      isNull,
    );
    await tester.tap(find.text('按修改重新估算营养'));
    await tester.pumpAndSettle();
    final correction = jsonDecode(requests.last.body) as Map<String, dynamic>;
    expect(correction['notes'], contains('一小碗'));
    expect(correction.containsKey('reviewed_foods'), isFalse);
    expect(find.textContaining('当前待确认估算约 234 千卡'), findsOneWidget);
    expect(
      tester
          .widget<TextFormField>(find.widgetWithText(TextFormField, '份量（g）'))
          .controller!
          .text,
      '180',
    );
  });
}

Uint8List _testPhotoBytes() => base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
);

Map<String, dynamic> _qualityPhotoJson(String name, int grams, int kcal) {
  final totals = _totals(kcal, 20, 35, 10);
  return {
    'image_asset_id': 'food-image',
    'meal_type': 'lunch',
    'eaten_at': '2026-10-16T04:00:00Z',
    'recognition': {'foods': [], 'assumptions': [], 'follow_up_questions': []},
    'calculation': {
      'items': [
        {
          'match': {
            'detected': {
              'name': name,
              'estimated_amount_g': '$grams',
              'amount_min_g': '$grams',
              'amount_max_g': '$grams',
              'confidence': 'medium',
            },
            'status': 'not_found',
          },
          'nutrition': {
            'minimum': totals,
            'estimated': totals,
            'maximum': totals,
          },
          'assumptions': [],
          'follow_up_questions': [],
        },
      ],
      'totals': {'minimum': totals, 'estimated': totals, 'maximum': totals},
      'is_complete': true,
    },
  };
}

Map<String, String> _totals(int kcal, int protein, int carbs, int fat) => {
  'kcal': '$kcal',
  'protein_g': '$protein',
  'carbs_g': '$carbs',
  'fat_g': '$fat',
};

http.Response _response(Object value) => http.Response.bytes(
  utf8.encode(jsonEncode(value)),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);
