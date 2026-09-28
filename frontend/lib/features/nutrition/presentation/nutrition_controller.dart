import 'package:flutter/foundation.dart';

import '../../../core/media/image_upload.dart';
import '../../../core/network/api_exception.dart';
import '../data/nutrition_repository.dart';
import '../domain/nutrition_models.dart';

class NutritionController extends ChangeNotifier {
  NutritionController(this._repository, {this.imageUploader});

  final NutritionRepository _repository;
  final Future<UploadedImage> Function(Uint8List)? imageUploader;

  DailyNutritionSummary? summary;
  WeeklyNutritionSummary? weeklySummary;
  List<NutritionEntry> entries = const [];
  List<FrequentFood> frequentFoods = const [];
  bool loading = false;
  bool submitting = false;
  String? errorMessage;

  Future<void> refresh() async {
    if (loading) return;
    loading = true;
    errorMessage = null;
    notifyListeners();
    try {
      final today = DateTime.now();
      final weekStart = DateTime(
        today.year,
        today.month,
        today.day,
      ).subtract(Duration(days: today.weekday - 1));
      final values = await Future.wait<Object>([
        _repository.getDailySummary(today),
        _repository.listEntries(today),
        _repository.getWeeklySummary(weekStart),
        _repository.listFrequentFoods(),
      ]);
      summary = values[0] as DailyNutritionSummary;
      entries = values[1] as List<NutritionEntry>;
      weeklySummary = values[2] as WeeklyNutritionSummary;
      frequentFoods = values[3] as List<FrequentFood>;
    } on ApiException catch (error) {
      errorMessage = error.message;
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<bool> add(ManualNutritionInput input) async {
    return _runMutation(() => _repository.createManualEntry(input));
  }

  Future<bool> addFood(FoodServingInput input) async {
    return _runMutation(() => _repository.createFoodEntry(input));
  }

  Future<NutritionPhotoDraft?> estimatePhoto({
    required Uint8List bytes,
    required String mealType,
  }) => _runQuery(() async {
    final uploader = imageUploader;
    if (uploader == null) {
      throw const ApiException(
        code: 'PHOTO_UPLOAD_UNAVAILABLE',
        message: '当前无法上传餐食照片',
      );
    }
    final uploaded = await uploader(bytes);
    return _repository.estimatePhoto(
      imageAssetId: uploaded.assetId,
      mealType: mealType,
    );
  });

  Future<bool> savePhotoEntry(NutritionPhotoEntryInput input) =>
      _runMutation(() => _repository.createPhotoEntry(input));

  Future<bool> editEntry(
    NutritionEntry entry,
    NutritionEntryEditInput input,
  ) async {
    return _runMutation(() => _repository.updateEntry(entry, input));
  }

  Future<bool> deleteEntry(NutritionEntry entry) async {
    return _runMutation(() => _repository.deleteEntry(entry));
  }

  Future<FoodSearchResult> searchFoods(String keyword) =>
      _repository.searchFoods(keyword);

  Future<FoodItem?> createCustomFood(CustomFoodInput input) async {
    if (submitting) return null;
    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      return await _repository.createCustomFood(input);
    } on ApiException catch (error) {
      errorMessage = error.message;
      return null;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }

  Future<FoodItem?> lookupBarcode(String code) =>
      _runQuery(() => _repository.getFoodByBarcode(code));

  Future<NutritionAdvice?> getAdvice(String foodName) =>
      _runQuery(() => _repository.getAdvice(foodName: foodName));

  Future<List<FlexibleMeal>> listFlexibleMeals() async =>
      await _runQuery(_repository.listFlexibleMeals) ?? const [];

  Future<List<RecipeSummary>> listRecipes() async =>
      await _runQuery(_repository.listRecipes) ?? const [];

  Future<NutritionTextDraft?> parseTextDraft({
    required String text,
    required String mealType,
  }) => _runQuery(
    () => _repository.parseTextDraft(text: text, mealType: mealType),
  );

  Future<bool> submitTextDraft(NutritionTextDraft draft) =>
      _runMutation(() => _repository.submitTextDraft(draft));

  Future<FlexibleMeal?> createFlexibleMeal({
    required DateTime date,
    required String label,
  }) =>
      _runQuery(() => _repository.createFlexibleMeal(date: date, label: label));

  Future<RecipeSummary?> createRecipe({
    required String name,
    required double servings,
    required FoodItem food,
    required double amountG,
  }) => _runQuery(
    () => _repository.createRecipe(
      name: name,
      servings: servings,
      food: food,
      amountG: amountG,
    ),
  );

  Future<T?> _runQuery<T>(Future<T> Function() operation) async {
    if (submitting) return null;
    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      return await operation();
    } on ApiException catch (error) {
      errorMessage = error.message;
      return null;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }

  Future<bool> _runMutation(Future<Object?> Function() operation) async {
    if (submitting) return false;
    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      await operation();
      await refresh();
      return true;
    } on ApiException catch (error) {
      errorMessage = error.message;
      return false;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }
}
