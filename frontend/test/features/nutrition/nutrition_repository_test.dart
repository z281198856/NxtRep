import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/nutrition/data/nutrition_repository.dart';
import 'package:nxtrep/features/nutrition/domain/nutrition_models.dart';

void main() {
  test(
    'creates a complete custom nutrition item with an idempotency key',
    () async {
      late http.Request captured;
      final httpClient = MockClient((request) async {
        captured = request;
        return _utf8Response(
          jsonEncode({
            'id': '00000000-0000-0000-0000-000000000041',
            'meal_type': 'lunch',
            'eaten_at': '2026-09-13T04:00:00Z',
            'items': [
              {'name': '鸡胸肉'},
            ],
            'totals': {
              'kcal': '165',
              'protein_g': '31',
              'carbs_g': '0',
              'fat_g': '3.6',
            },
            'version': 1,
          }),
          201,
        );
      });
      final repository = NutritionRepository(
        ApiClient(
          config: ApiConfig(
            baseUri: Uri.parse('https://api.example.test/api/v1'),
          ),
          accessTokenProvider: () => 'access',
          httpClient: httpClient,
        ),
      );

      final result = await repository.createManualEntry(
        const ManualNutritionInput(
          name: '鸡胸肉',
          mealType: 'lunch',
          amountG: 100,
          kcal: 165,
          proteinG: 31,
          carbsG: 0,
          fatG: 3.6,
        ),
      );
      final body = jsonDecode(captured.body) as Map<String, dynamic>;
      final item =
          (body['items'] as List<dynamic>).single as Map<String, dynamic>;

      expect(captured.url.path, '/api/v1/nutrition/entries');
      expect(captured.headers['Idempotency-Key'], isNotEmpty);
      expect(item['food_version_id'], isNull);
      expect(item['basis_amount_g'], 100.0);
      expect(item['source'], 'user');
      expect(item['confidence'], 'confirmed');
      expect(DateTime.parse(body['eaten_at'] as String).isUtc, isTrue);
      expect(result.totals.proteinG, 31);
    },
  );

  test('searches foods and creates a serving-based entry', () async {
    final requests = <http.Request>[];
    final repository = _repositoryWith(
      MockClient((request) async {
        requests.add(request);
        if (request.url.path.endsWith('/foods/search')) {
          return _utf8Response(
            jsonEncode({
              'list': [_foodJson()],
              'total': 1,
              'page': 1,
              'page_size': 50,
              'has_more': false,
            }),
            200,
          );
        }
        return _utf8Response(jsonEncode(_entryJson()), 201);
      }),
    );

    final food = (await repository.searchFoods(' 鸡胸肉 ')).items.single;
    final entry = await repository.createFoodEntry(
      FoodServingInput(
        food: food,
        amountG: 150,
        mealType: 'dinner',
        isFlexibleMeal: true,
        notes: '训练后',
      ),
    );
    final body = jsonDecode(requests[1].body) as Map<String, dynamic>;
    final item =
        (body['items'] as List<dynamic>).single as Map<String, dynamic>;

    expect(requests[0].url.queryParameters['keyword'], '鸡胸肉');
    expect(item, {
      'food_version_id': '00000000-0000-0000-0000-000000000052',
      'amount_g': 150.0,
    });
    expect(body['is_flexible_meal'], isTrue);
    expect(entry.items.single.amountG, 150);
  });

  test('creates a custom food with nutrition basis data', () async {
    late http.Request captured;
    final repository = _repositoryWith(
      MockClient((request) async {
        captured = request;
        return _utf8Response(jsonEncode(_foodJson(name: '自制燕麦杯')), 201);
      }),
    );

    final food = await repository.createCustomFood(
      const CustomFoodInput(
        name: '自制燕麦杯',
        brand: '家制',
        basisAmountG: 250,
        kcal: 360,
        proteinG: 18,
        carbsG: 52,
        fatG: 10,
      ),
    );
    final body = jsonDecode(captured.body) as Map<String, dynamic>;

    expect(captured.url.path, '/api/v1/foods');
    expect(captured.headers['Idempotency-Key'], isNotEmpty);
    expect(body['basis_amount_g'], 250.0);
    expect(body['brand'], '家制');
    expect(food.name, '自制燕麦杯');
  });

  test('updates an entry and approves its deletion confirmation', () async {
    final requests = <http.Request>[];
    final repository = _repositoryWith(
      MockClient((request) async {
        requests.add(request);
        if (request.method == 'PATCH') {
          return _utf8Response(jsonEncode(_entryJson(version: 2)), 200);
        }
        if (request.method == 'DELETE') {
          return _utf8Response(
            jsonEncode({
              'confirmation_id': '00000000-0000-0000-0000-000000000061',
              'operation_type': 'nutrition_entry_delete',
              'status': 'pending',
              'before': {},
              'after': {},
              'impact': '删除饮食记录',
            }),
            200,
          );
        }
        if (request.method == 'GET') {
          return _utf8Response(
            jsonEncode({
              'id': '00000000-0000-0000-0000-000000000061',
              'version': 3,
            }),
            200,
          );
        }
        return _utf8Response(
          jsonEncode({
            'id': '00000000-0000-0000-0000-000000000061',
            'status': 'succeeded',
            'result': {},
            'executed_at': '2026-09-22T08:00:00Z',
            'version': 4,
          }),
          200,
        );
      }),
    );
    final original = NutritionEntry.fromJson(_entryJson());
    final edited = await repository.updateEntry(
      original,
      NutritionEntryEditInput(
        mealType: 'dinner',
        items: [original.items.single.withAmount(180)],
        isFlexibleMeal: false,
        notes: '增加份量',
      ),
    );
    await repository.deleteEntry(edited);

    final updateBody = jsonDecode(requests[0].body) as Map<String, dynamic>;
    final deleteBody = jsonDecode(requests[1].body) as Map<String, dynamic>;
    final approveBody = jsonDecode(requests[3].body) as Map<String, dynamic>;
    expect(updateBody['expected_version'], 1);
    expect(updateBody['reason'], isNotEmpty);
    expect(deleteBody['expected_version'], 2);
    expect(requests[2].url.path, contains('/confirmations/'));
    expect(approveBody['expected_version'], 3);
    expect(requests[3].headers['Idempotency-Key'], isNotEmpty);
  });

  test('loads frequent foods and weekly summary', () async {
    final repository = _repositoryWith(
      MockClient((request) async {
        if (request.url.path.endsWith('/foods/frequent')) {
          return _utf8Response(
            jsonEncode([
              {..._foodJson(), 'use_count': 4},
            ]),
            200,
          );
        }
        return _utf8Response(
          jsonEncode({
            'start_date': '2026-09-21',
            'end_date': '2026-09-27',
            'daily_average': {
              'kcal': '1800',
              'protein_g': '120',
              'carbs_g': '190',
              'fat_g': '55',
            },
            'total_entries': 8,
            'recorded_days': 2,
            'flexible_meals': 1,
            'record_completeness': '0.2857',
          }),
          200,
        );
      }),
    );

    final frequent = await repository.listFrequentFoods();
    final weekly = await repository.getWeeklySummary(DateTime(2026, 9, 21));

    expect(frequent.single.useCount, 4);
    expect(weekly.totalEntries, 8);
    expect(weekly.dailyAverage.proteinG, 120);
  });

  test('estimates a meal photo and saves reviewed nutrition values', () async {
    final requests = <http.Request>[];
    const imageId = '00000000-0000-0000-0000-000000000099';
    final repository = _repositoryWith(
      MockClient((request) async {
        requests.add(request);
        if (request.url.path.endsWith('/entry-drafts:estimate-image')) {
          final totals = {
            'kcal': '300',
            'protein_g': '20',
            'carbs_g': '35',
            'fat_g': '10',
          };
          return _utf8Response(
            jsonEncode({
              'image_asset_id': imageId,
              'meal_type': 'lunch',
              'eaten_at': '2026-09-28T04:00:00Z',
              'recognition': {
                'foods': [],
                'assumptions': ['油量不可见'],
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
                      'minimum': totals,
                      'estimated': totals,
                      'maximum': totals,
                    },
                    'assumptions': [],
                    'follow_up_questions': [],
                  },
                ],
                'totals': {
                  'minimum': totals,
                  'estimated': totals,
                  'maximum': totals,
                },
                'is_complete': true,
              },
            }),
            200,
          );
        }
        return _utf8Response(jsonEncode(_entryJson()), 201);
      }),
    );

    final draft = await repository.estimatePhoto(
      imageAssetId: imageId,
      mealType: 'lunch',
    );
    await repository.createPhotoEntry(
      NutritionPhotoEntryInput(
        mealType: draft.mealType,
        eatenAt: draft.eatenAt,
        imageAssetId: draft.imageAssetId,
        items: const [
          NutritionEntryItem(
            name: '鸡肉饭',
            amountG: 250,
            basisAmountG: 250,
            kcal: 300,
            proteinG: 20,
            carbsG: 35,
            fatG: 10,
            source: 'model_estimated',
            confidence: 'low',
          ),
        ],
      ),
    );
    final estimateBody = jsonDecode(requests[0].body) as Map<String, dynamic>;
    final saveBody = jsonDecode(requests[1].body) as Map<String, dynamic>;
    final savedItem =
        (saveBody['items'] as List<dynamic>).single as Map<String, dynamic>;

    expect(estimateBody['image_asset_id'], imageId);
    expect(draft.items.single.amountMaxG, 300);
    expect(draft.totals.estimated.kcal, 300);
    expect(savedItem['source'], 'model_estimated');
    expect(savedItem['confidence'], 'low');
    expect(savedItem['protein_g'], 20.0);
    expect(requests[1].headers['Idempotency-Key'], isNotEmpty);
  });
}

NutritionRepository _repositoryWith(MockClient client) => NutritionRepository(
  ApiClient(
    config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
    accessTokenProvider: () => 'access',
    httpClient: client,
  ),
);

Map<String, dynamic> _foodJson({String name = '鸡胸肉'}) => {
  'id': '00000000-0000-0000-0000-000000000051',
  'food_version_id': '00000000-0000-0000-0000-000000000052',
  'name': name,
  'brand': null,
  'barcode': null,
  'state': 'active',
  'basis_amount_g': '100',
  'kcal': '165',
  'protein_g': '31',
  'carbs_g': '0',
  'fat_g': '3.6',
  'source': 'catalog',
  'confidence': 'confirmed',
};

Map<String, dynamic> _entryJson({int version = 1}) => {
  'id': '00000000-0000-0000-0000-000000000041',
  'meal_type': 'dinner',
  'eaten_at': '2026-09-22T04:00:00Z',
  'items': [
    {
      'food_version_id': '00000000-0000-0000-0000-000000000052',
      'amount_g': '150',
      'name': '鸡胸肉',
      'basis_amount_g': '100',
      'kcal': '165',
      'protein_g': '31',
      'carbs_g': '0',
      'fat_g': '3.6',
      'source': 'catalog',
      'confidence': 'confirmed',
    },
  ],
  'totals': {
    'kcal': '247.5',
    'protein_g': '46.5',
    'carbs_g': '0',
    'fat_g': '5.4',
  },
  'is_flexible_meal': true,
  'notes': '训练后',
  'version': version,
};

http.Response _utf8Response(String body, int statusCode) => http.Response.bytes(
  utf8.encode(body),
  statusCode,
  headers: {'content-type': 'application/json; charset=utf-8'},
);
