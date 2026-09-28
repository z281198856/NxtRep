import 'package:uuid/uuid.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/api_exception.dart';
import '../domain/nutrition_models.dart';

class NutritionRepository {
  NutritionRepository(this._apiClient, {Uuid? uuid})
    : _uuid = uuid ?? const Uuid();

  final ApiClient _apiClient;
  final Uuid _uuid;

  Future<NutritionPhotoDraft> estimatePhoto({
    required String imageAssetId,
    required String mealType,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/nutrition/entry-drafts:estimate-image',
        timeout: const Duration(seconds: 90),
        body: {
          'image_asset_id': imageAssetId,
          'meal_type': mealType,
          'eaten_at': DateTime.now().toUtc().toIso8601String(),
          'notes': null,
        },
      ),
      context: '餐食照片营养估算接口',
    );
    return NutritionPhotoDraft.fromJson(json);
  }

  Future<NutritionEntry> createPhotoEntry(
    NutritionPhotoEntryInput input,
  ) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/nutrition/entries',
        idempotencyKey: _uuid.v4(),
        body: {
          'meal_type': input.mealType,
          'eaten_at': input.eatenAt.toUtc().toIso8601String(),
          'items': input.items.map((item) => item.toInputJson()).toList(),
          'is_flexible_meal': false,
          'notes': 'AI 照片估算，经用户核对；图片 ID：${input.imageAssetId}',
        },
      ),
      context: '保存照片饮食记录接口',
    );
    return NutritionEntry.fromJson(json);
  }

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

  Future<FoodItem> getFoodByBarcode(String code) async {
    final json = expectJsonObject(
      await _apiClient.get('/foods/barcodes/${code.trim()}'),
      context: '食品条码查询接口',
    );
    return FoodItem.fromJson(json);
  }

  Future<NutritionAdvice> getAdvice({
    required String foodName,
    double? amountG,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/nutrition/advice',
        body: {
          'food_name': foodName.trim(),
          'amount_g': amountG,
          'on_date': _dateOnly(DateTime.now()),
        },
      ),
      context: '营养建议接口',
    );
    return NutritionAdvice.fromJson(json);
  }

  Future<List<FlexibleMeal>> listFlexibleMeals() async {
    final value = await _apiClient.get('/nutrition/flexible-meals');
    if (value is! List<dynamic>) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '自由餐接口返回格式不正确',
      );
    }
    return value
        .map(
          (item) =>
              FlexibleMeal.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList(growable: false);
  }

  Future<FlexibleMeal> createFlexibleMeal({
    required DateTime date,
    required String label,
    String? notes,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/nutrition/flexible-meals',
        idempotencyKey: _uuid.v4(),
        body: {
          'scheduled_date': _dateOnly(date),
          'label': label.trim(),
          'notes': notes,
        },
      ),
      context: '新增自由餐接口',
    );
    return FlexibleMeal.fromJson(json);
  }

  Future<NutritionTextDraft> parseTextDraft({
    required String text,
    required String mealType,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/nutrition/entry-drafts:parse-text',
        idempotencyKey: _uuid.v4(),
        body: {
          'text': text.trim(),
          'meal_type': mealType,
          'eaten_at': DateTime.now().toUtc().toIso8601String(),
          'is_flexible_meal': false,
          'notes': null,
        },
      ),
      context: '自然语言饮食识别接口',
    );
    return NutritionTextDraft.fromJson(json);
  }

  Future<void> submitTextDraft(NutritionTextDraft draft) async {
    final submit = expectJsonObject(
      await _apiClient.post(
        '/nutrition/entry-drafts/${draft.id}/submit',
        idempotencyKey: _uuid.v4(),
        body: {'expected_version': draft.version},
      ),
      context: '提交智能饮食记录接口',
    );
    final confirmationId = submit['confirmation_id'] as String;
    final detail = expectJsonObject(
      await _apiClient.get('/confirmations/$confirmationId'),
      context: '饮食记录确认单接口',
    );
    final result = expectJsonObject(
      await _apiClient.post(
        '/confirmations/$confirmationId/approve',
        idempotencyKey: _uuid.v4(),
        body: {'expected_version': detail['version'] as int},
      ),
      context: '确认智能饮食记录接口',
    );
    if (result['status'] != 'succeeded') {
      throw const ApiException(
        code: 'NUTRITION_DRAFT_FAILED',
        message: '智能饮食记录未能保存，请重试',
      );
    }
  }

  Future<List<RecipeSummary>> listRecipes() async {
    final value = await _apiClient.get(
      '/recipes',
      query: const {'page': '1', 'page_size': '50'},
    );
    if (value is! List<dynamic>) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '食谱接口返回格式不正确',
      );
    }
    return value
        .map(
          (item) =>
              RecipeSummary.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList(growable: false);
  }

  Future<RecipeSummary> createRecipe({
    required String name,
    required double servings,
    required FoodItem food,
    required double amountG,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/recipes',
        idempotencyKey: _uuid.v4(),
        body: {
          'name': name.trim(),
          'servings': servings,
          'items': [
            {'food_version_id': food.foodVersionId, 'amount_g': amountG},
          ],
          'notes': null,
        },
      ),
      context: '新增食谱接口',
    );
    return RecipeSummary.fromJson(json);
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
