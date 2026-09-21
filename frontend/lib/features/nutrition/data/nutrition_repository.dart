import 'package:uuid/uuid.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/api_exception.dart';
import '../domain/nutrition_models.dart';

class NutritionRepository {
  NutritionRepository(this._apiClient, {Uuid? uuid})
    : _uuid = uuid ?? const Uuid();

  final ApiClient _apiClient;
  final Uuid _uuid;

  Future<DailyNutritionSummary> getDailySummary(DateTime date) async {
    final json = expectJsonObject(
      await _apiClient.get(
        '/nutrition/daily-summary',
        query: {'date': _dateOnly(date)},
      ),
      context: '每日营养汇总接口',
    );
    return DailyNutritionSummary.fromJson(json);
  }

  Future<List<NutritionEntry>> listEntries(DateTime date) async {
    final value = await _apiClient.get(
      '/nutrition/entries',
      query: {'date': _dateOnly(date)},
    );
    if (value is! List<dynamic>) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '饮食记录接口返回格式不正确',
      );
    }
    return value
        .map((item) => NutritionEntry.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<NutritionEntry> createManualEntry(ManualNutritionInput input) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/nutrition/entries',
        idempotencyKey: _uuid.v4(),
        body: {
          'meal_type': input.mealType,
          'eaten_at': DateTime.now().toUtc().toIso8601String(),
          'items': [
            {
              'food_version_id': null,
              'amount_g': input.amountG,
              'name': input.name,
              'basis_amount_g': input.amountG,
              'kcal': input.kcal,
              'protein_g': input.proteinG,
              'carbs_g': input.carbsG,
              'fat_g': input.fatG,
              'source': 'user',
              'confidence': 'confirmed',
            },
          ],
          'is_flexible_meal': false,
          'notes': null,
        },
      ),
      context: '新增饮食记录接口',
    );
    return NutritionEntry.fromJson(json);
  }

  String _dateOnly(DateTime value) =>
      '${value.year.toString().padLeft(4, '0')}-'
      '${value.month.toString().padLeft(2, '0')}-'
      '${value.day.toString().padLeft(2, '0')}';
}
