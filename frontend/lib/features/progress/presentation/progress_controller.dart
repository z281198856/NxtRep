import 'package:flutter/foundation.dart';

import '../../../core/network/api_exception.dart';
import '../data/body_repository.dart';
import '../domain/body_models.dart';

class ProgressController extends ChangeNotifier {
  ProgressController(this._repository);

  final BodyRepository _repository;

  List<BodyMeasurement> measurements = const [];
  List<BodyTrendPoint> trend = const [];
  List<PersonalRecord> personalRecords = const [];
  ProgressOverview? overview;
  BodyMetric selectedMetric = BodyMetric.weight;
  int selectedDays = 30;
  bool loading = false;
  bool trendLoading = false;
  bool submitting = false;
  String? errorMessage;

  Future<void> refresh() async {
    if (loading) return;
    loading = true;
    errorMessage = null;
    notifyListeners();
    try {
      final values = await Future.wait<Object>([
        _repository.listMeasurements(),
        _repository.getOverview(days: selectedDays),
        _repository.getBodyTrend(metric: selectedMetric, days: selectedDays),
        _repository.listPersonalRecords(),
      ]);
      measurements = values[0] as List<BodyMeasurement>;
      overview = values[1] as ProgressOverview;
      trend = values[2] as List<BodyTrendPoint>;
      personalRecords = values[3] as List<PersonalRecord>;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> selectMetric(BodyMetric metric) async {
    if (selectedMetric == metric || trendLoading) return;
    selectedMetric = metric;
    trendLoading = true;
    errorMessage = null;
    notifyListeners();
    try {
      trend = await _repository.getBodyTrend(
        metric: selectedMetric,
        days: selectedDays,
      );
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
    } finally {
      trendLoading = false;
      notifyListeners();
    }
  }

  Future<void> selectRange(int days) async {
    if (selectedDays == days || loading) return;
    selectedDays = days;
    await refresh();
  }

  Future<bool> add(BodyMeasurementInput input) async {
    if (submitting) return false;
    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      await _repository.createMeasurement(input);
      await refresh();
      return true;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return false;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }

  Future<bool> update(
    BodyMeasurement current,
    BodyMeasurementInput input,
  ) async {
    if (submitting) return false;
    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      await _repository.updateMeasurement(current, input);
      await refresh();
      return true;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return false;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }

  String _messageFor(ApiException error) => switch (error.code) {
    'BODY_MEASUREMENT_VERSION_CONFLICT' => '这条记录已经更新，请刷新后重试',
    'BODY_MEASUREMENT_NOT_FOUND' => '这条身体记录已经不存在',
    'INVALID_DATE_RANGE' => '查询日期范围不正确',
    _ => error.message,
  };
}
