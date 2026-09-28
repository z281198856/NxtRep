import 'dart:convert';

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
    await tester.tap(find.text('识别食物并估算营养'));
    await tester.pumpAndSettle();

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
    expect(item['amount_g'], 300);
    expect(item['kcal'], 360);
    expect(item['source'], 'model_estimated');
    expect(find.text('打开拍照记餐'), findsOneWidget);
  });
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
