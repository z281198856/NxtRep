import 'package:flutter/foundation.dart';

import '../../../core/network/api_exception.dart';
import '../data/nutrition_repository.dart';
import '../domain/nutrition_models.dart';

class NutritionController extends ChangeNotifier {
  NutritionController(this._repository);

  final NutritionRepository _repository;

  DailyNutritionSummary? summary;
  List<NutritionEntry> entries = const [];
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
      final values = await Future.wait<Object>([
        _repository.getDailySummary(today),
        _repository.listEntries(today),
      ]);
      summary = values[0] as DailyNutritionSummary;
      entries = values[1] as List<NutritionEntry>;
    } on ApiException catch (error) {
      errorMessage = error.message;
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<bool> add(ManualNutritionInput input) async {
    if (submitting) return false;
    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      await _repository.createManualEntry(input);
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
