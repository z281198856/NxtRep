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

  Future<WeeklyNutritionSummary> getWeeklySummary(DateTime startDate) async {
    final json = expectJsonObject(
      await _apiClient.get(
        '/nutrition/weekly-summary',
        query: {'start_date': _dateOnly(startDate)},
      ),
      context: '每周营养汇总接口',
    );
    return WeeklyNutritionSummary.fromJson(json);
  }

  Future<FoodSearchResult> searchFoods(String keyword) async {
    final json = expectJsonObject(
      await _apiClient.get(
        '/foods/search',
        query: {'keyword': keyword.trim(), 'page': '1', 'page_size': '50'},
      ),
      context: '食品搜索接口',
    );
    return FoodSearchResult.fromJson(json);
  }

  Future<List<FrequentFood>> listFrequentFoods() async {
    final value = await _apiClient.get(
      '/foods/frequent',
      query: const {'limit': '10'},
    );
    if (value is! List<dynamic>) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '常用食品接口返回格式不正确',
      );
    }
    return value
        .map(
          (item) =>
              FrequentFood.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList(growable: false);
  }

  Future<FoodItem> createCustomFood(CustomFoodInput input) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/foods',
        idempotencyKey: _uuid.v4(),
        body: input.toJson(),
      ),
      context: '新增自定义食品接口',
    );
    return FoodItem.fromJson(json);
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
          'is_flexible_meal': input.isFlexibleMeal,
          'notes': input.notes,
        },
      ),
      context: '新增饮食记录接口',
    );
    return NutritionEntry.fromJson(json);
  }

  Future<NutritionEntry> createFoodEntry(FoodServingInput input) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/nutrition/entries',
        idempotencyKey: _uuid.v4(),
        body: {
          'meal_type': input.mealType,
          'eaten_at': DateTime.now().toUtc().toIso8601String(),
          'items': [
            {
              'food_version_id': input.food.foodVersionId,
              'amount_g': input.amountG,
            },
          ],
          'is_flexible_meal': input.isFlexibleMeal,
          'notes': input.notes,
        },
      ),
      context: '食品记录接口',
    );
    return NutritionEntry.fromJson(json);
  }

  Future<NutritionEntry> updateEntry(
    NutritionEntry entry,
    NutritionEntryEditInput input,
  ) async {
    final json = expectJsonObject(
      await _apiClient.patch(
        '/nutrition/entries/${entry.id}',
        body: {
          'meal_type': input.mealType,
          'items': input.items.map((item) => item.toInputJson()).toList(),
          'is_flexible_meal': input.isFlexibleMeal,
          'notes': input.notes,
          'reason': '用户在移动端编辑饮食记录',
          'expected_version': entry.version,
        },
      ),
      context: '编辑饮食记录接口',
    );
    return NutritionEntry.fromJson(json);
  }

  Future<void> deleteEntry(NutritionEntry entry) async {
    final submit = expectJsonObject(
      await _apiClient.delete(
        '/nutrition/entries/${entry.id}',
        body: {'expected_version': entry.version, 'reason': '用户在移动端删除饮食记录'},
      ),
      context: '删除饮食记录确认接口',
    );
    final confirmationId = submit['confirmation_id'] as String;
    final detail = expectJsonObject(
      await _apiClient.get('/confirmations/$confirmationId'),
      context: '饮食记录删除确认单接口',
    );
    final result = expectJsonObject(
      await _apiClient.post(
        '/confirmations/$confirmationId/approve',
        idempotencyKey: _uuid.v4(),
        body: {'expected_version': detail['version'] as int},
      ),
      context: '执行饮食记录删除接口',
    );
    if (result['status'] != 'succeeded') {
      throw const ApiException(
        code: 'NUTRITION_DELETE_FAILED',
        message: '饮食记录未能删除，请刷新后重试',
      );
    }
  }

  String _dateOnly(DateTime value) =>
      '${value.year.toString().padLeft(4, '0')}-'
      '${value.month.toString().padLeft(2, '0')}-'
      '${value.day.toString().padLeft(2, '0')}';
}
