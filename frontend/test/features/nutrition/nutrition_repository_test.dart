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
        return http.Response(
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
          headers: {'content-type': 'application/json; charset=utf-8'},
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
}
