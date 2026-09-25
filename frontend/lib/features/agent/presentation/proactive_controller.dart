import 'package:flutter/foundation.dart';

import '../../../core/network/api_exception.dart';
import '../data/proactive_repository.dart';
import '../domain/proactive_models.dart';

class ProactiveController extends ChangeNotifier {
  ProactiveController(this._repository);

  final ProactiveRepository _repository;

  ProactiveSettings? settings;
  List<ProactiveNotice> notices = const [];
  bool loading = false;
  bool updating = false;
  String? errorMessage;

  bool get enabled => settings?.coachEnabled ?? false;

  List<ProactiveNotice> _visibleNotices(List<ProactiveNotice> values) =>
      settings?.frequency == 'important_only'
      ? values.where((item) => item.kind != 'nutrition_log_gap').toList()
      : values;

  Future<void> refresh() async {
    if (loading) return;
    loading = true;
    errorMessage = null;
    notifyListeners();
    try {
      settings = await _repository.getSettings();
      if (enabled) await _repository.review();
      notices = enabled
          ? _visibleNotices(await _repository.listUnread())
          : const [];
    } on ApiException catch (error) {
      errorMessage = error.message;
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> setEnabled(bool value) async {
    final current = settings;
    if (current == null || updating || loading) return;
    updating = true;
    errorMessage = null;
    notifyListeners();
    try {
      settings = await _repository.setEnabled(current, value);
      if (enabled) await _repository.review();
      notices = enabled
          ? _visibleNotices(await _repository.listUnread())
          : const [];
    } on ApiException catch (error) {
      errorMessage = error.message;
    } finally {
      updating = false;
      notifyListeners();
    }
  }

  Future<void> setFrequency(String value) async {
    final current = settings;
    if (current == null ||
        updating ||
        loading ||
        !enabled ||
        current.frequency == value) {
      return;
    }
    updating = true;
    errorMessage = null;
    notifyListeners();
    try {
      settings = await _repository.setFrequency(current, value);
      await _repository.review();
      notices = _visibleNotices(await _repository.listUnread());
    } on ApiException catch (error) {
      errorMessage = error.message;
    } finally {
      updating = false;
      notifyListeners();
    }
  }

  Future<void> markRead(ProactiveNotice notice) async {
    try {
      await _repository.markRead(notice.id);
      notices = notices.where((item) => item.id != notice.id).toList();
      notifyListeners();
    } on ApiException catch (error) {
      errorMessage = error.message;
      notifyListeners();
    }
  }

  Future<void> submitFeedback(ProactiveNotice notice, String rating) async {
    if (notice.feedbackRating == rating) return;
    errorMessage = null;
    try {
      final updated = await _repository.submitFeedback(notice.id, rating);
      notices = [
        for (final item in notices) item.id == notice.id ? updated : item,
      ];
      notifyListeners();
    } on ApiException catch (error) {
      errorMessage = error.message;
      notifyListeners();
    }
  }
}
