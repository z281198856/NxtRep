import 'package:flutter/foundation.dart';

import '../../../core/media/image_upload.dart';
import '../../../core/network/api_exception.dart';
import '../../../core/state/lifecycle_notifier.dart';
import '../data/nutrition_repository.dart';
import '../domain/nutrition_models.dart';
import '../domain/nutrition_date.dart';
import '../domain/water_entry.dart';

class NutritionController extends LifecycleNotifier {
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
  String? photoActivity;
  bool savedLocally = false;
  Uint8List? _photoSource;
  UploadedImage? _uploadedPhoto;
  DateTime _selectedDate = nutritionToday();
  int _dateRequest = 0;

  DateTime get selectedDate => _selectedDate;

  Future<void> selectDate(DateTime date) async {
    final day = DateTime(date.year, date.month, date.day);
    if (day == _selectedDate) return;
    _selectedDate = day;
    await _loadSelectedDate();
  }

  Future<void> refresh() async {
    if (loading || isDisposed) return;
    await _loadSelectedDate();
  }

  Future<void> _loadSelectedDate() async {
    final request = ++_dateRequest;
    final date = _selectedDate;
    loading = true;
    errorMessage = null;
    summary = null;
    entries = const [];
    weeklySummary = null;
    notifyListeners();
    try {
      final weekStart = DateTime(
        date.year,
        date.month,
        date.day,
      ).subtract(Duration(days: date.weekday - 1));
      final values = await Future.wait<Object>([
        _repository.getDailySummary(date),
        _repository.listEntries(date),
        _repository.getWeeklySummary(weekStart),
        _repository.listFrequentFoods(),
      ]);
      if (request != _dateRequest) return;
      summary = values[0] as DailyNutritionSummary;
      entries = values[1] as List<NutritionEntry>;
      weeklySummary = values[2] as WeeklyNutritionSummary;
      frequentFoods = values[3] as List<FrequentFood>;
    } on ApiException catch (error) {
      if (request == _dateRequest) errorMessage = error.message;
    } finally {
      if (request == _dateRequest) {
        loading = false;
        notifyListeners();
      }
    }
  }

  @override
  void dispose() {
    // Ignore responses that arrive after this account's controller is closed.
    _dateRequest++;
    _photoSource = null;
    _uploadedPhoto = null;
    super.dispose();
  }

  Future<bool> add(
    ManualNutritionInput input, {
    DateTime? date,
    String? draftKey,
  }) async {
    final eatenAt = nutritionRecordedAt(date ?? selectedDate, input.mealType);
    return _runMutation(
      () => _repository.createManualEntry(
        input,
        eatenAt: eatenAt,
        draftKey: draftKey,
      ),
    );
  }

  Future<List<NutritionEntry>> recentEntries(DateTime through) =>
      _repository.recentEntries(through);

  Future<bool> copyEntry(
    NutritionEntry source,
    String mealType,
    DateTime date,
  ) => _runMutation(
    () => _repository.copyEntry(
      source,
      mealType,
      nutritionRecordedAt(date, mealType),
    ),
  );

  Future<List<WaterEntry>> listWater(DateTime date) =>
      _repository.listWater(date);

  Future<bool> addWater(
    int amountMl,
    DateTime consumedAt, {
    String? draftKey,
  }) => _runMutation(
    () => _repository.addWater(amountMl, consumedAt, draftKey: draftKey),
  );

  Future<bool> deleteWater(String id) =>
      _runMutation(() => _repository.deleteWater(id));

  Future<bool> addFood(FoodServingInput input, {DateTime? date}) async {
    final eatenAt = nutritionRecordedAt(date ?? selectedDate, input.mealType);
    return _runMutation(
      () => _repository.createFoodEntry(input, eatenAt: eatenAt),
    );
  }

  Future<NutritionPhotoDraft?> estimatePhoto({
    required Uint8List bytes,
    required String mealType,
    DateTime? eatenAt,
    String? notes,
  }) => _runPhotoQuery(() async {
    final uploader = imageUploader;
    if (uploader == null) {
      throw const ApiException(
        code: 'PHOTO_UPLOAD_UNAVAILABLE',
        message: '当前无法上传餐食照片',
      );
    }
    if (!identical(_photoSource, bytes)) {
      _photoSource = bytes;
      _uploadedPhoto = null;
    }
    if (_uploadedPhoto == null) {
      photoActivity = '正在上传照片…';
      notifyListeners();
      final uploaded = await uploader(bytes);
      if (isDisposed) return null;
      _uploadedPhoto = uploaded;
    }
    photoActivity = '正在识别食物并估算营养，通常需要几十秒…';
    notifyListeners();
    return _repository.estimatePhoto(
      imageAssetId: _uploadedPhoto!.assetId,
      mealType: mealType,
      eatenAt: eatenAt,
      notes: notes,
    );
  });

  Future<NutritionPhotoDraft?> reestimatePhoto({
    required NutritionPhotoDraft draft,
    List<Map<String, dynamic>>? reviewedFoods,
    String? notes,
  }) => _runPhotoQuery(
    () => _repository.estimatePhoto(
      imageAssetId: draft.imageAssetId,
      mealType: draft.mealType,
      eatenAt: draft.eatenAt,
      reviewedFoods: reviewedFoods,
      notes: notes,
    ),
  );

  Future<bool> savePhotoEntry(
    NutritionPhotoEntryInput input, {
    String? draftKey,
  }) => _runMutation(
    () => _repository.createPhotoEntry(input, draftKey: draftKey),
  );

  Future<NutritionPhotoDraft?> _runPhotoQuery(
    Future<NutritionPhotoDraft?> Function() operation,
  ) async {
    if (submitting || isDisposed) return null;
    submitting = true;
    errorMessage = null;
    photoActivity = '正在按当前内容重新估算…';
    notifyListeners();
    try {
      final result = await operation();
      return isDisposed ? null : result;
    } on ApiException catch (error) {
      if (error.code == 'IMAGE_ASSET_NOT_FOUND') _uploadedPhoto = null;
      errorMessage = switch (error.code) {
        'VISION_MODEL_BUSY' => '识别服务当前繁忙，照片和填写内容已保留，请稍后重试。',
        'REQUEST_TIMEOUT' ||
        'NUTRITION_IMAGE_TIMEOUT' ||
        'NUTRITION_IMAGE_UNAVAILABLE' => '这次识别等待超时或连接中断，照片和填写内容已保留，可重新识别。',
        'NETWORK_ERROR' => '连接中断，照片和填写内容已保留，请检查网络后重试。',
        'IMAGE_ASSET_NOT_FOUND' => '已上传的照片暂不可用，请重试，系统会重新上传。',
        'IMAGE_ASSET_NOT_READY' => '照片仍在处理中，请稍后重新识别。',
        _ => error.message,
      };
      return null;
    } on Object {
      errorMessage = '照片处理或识别结果异常，已保留当前内容，请重新识别。';
      return null;
    } finally {
      submitting = false;
      photoActivity = null;
      notifyListeners();
    }
  }

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
    if (submitting || isDisposed) return null;
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
    if (submitting || isDisposed) return false;
    submitting = true;
    savedLocally = false;
    errorMessage = null;
    notifyListeners();
    try {
      await operation();
      await refresh();
      return true;
    } on ApiException catch (error) {
      if (error.code == 'RECORD_SAVED_LOCALLY') {
        savedLocally = true;
        return true;
      }
      errorMessage = error.message;
      return false;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }
}
