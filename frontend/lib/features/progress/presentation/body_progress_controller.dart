import 'package:flutter/foundation.dart';

import '../../../core/media/image_upload.dart';
import '../../../core/network/api_exception.dart';
import '../data/body_progress_repository.dart';
import '../domain/body_progress_models.dart';

typedef BodyImageUploader = Future<UploadedImage> Function(Uint8List bytes);

class BodyProgressController extends ChangeNotifier {
  BodyProgressController(this._repository, this._uploader);

  final BodyProgressRepository _repository;
  final BodyImageUploader _uploader;

  List<BodyProgressPhoto> photos = const [];
  List<ProgressReport> reports = const [];
  final Map<String, Uint8List> localPreviews = {};
  final Map<String, ImageDownloadIntent> downloads = {};
  final Set<String> loadingImages = {};
  bool loading = false;
  bool uploading = false;
  bool generatingReport = false;
  String? analyzingPhotoId;
  BodyPhotoAssessment? comparison;
  String? errorMessage;

  Future<void> refresh() async {
    if (loading) return;
    loading = true;
    errorMessage = null;
    notifyListeners();
    try {
      final result = await Future.wait<Object>([
        _repository.listPhotos(),
        _repository.listReports(),
      ]);
      photos = result[0] as List<BodyProgressPhoto>;
      reports = result[1] as List<ProgressReport>;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
    } on Object {
      errorMessage = '身体进度数据格式异常，请稍后重试';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<bool> addPhoto({
    required Uint8List bytes,
    required BodyPhotoView view,
    required DateTime capturedAt,
    String? notes,
  }) async {
    if (uploading) return false;
    uploading = true;
    errorMessage = null;
    notifyListeners();
    try {
      final uploaded = await _uploader(bytes);
      final photo = await _repository.createPhoto(
        imageAssetId: uploaded.assetId,
        capturedAt: capturedAt,
        view: view,
        notes: notes,
      );
      localPreviews[photo.imageAssetId] = uploaded.bytes;
      photos = [photo, ...photos];
      return true;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return false;
    } on Object {
      errorMessage = '图片读取失败，请重新选择';
      return false;
    } finally {
      uploading = false;
      notifyListeners();
    }
  }

  Future<void> ensureDownload(BodyProgressPhoto photo) async {
    final current = downloads[photo.imageAssetId];
    if (localPreviews.containsKey(photo.imageAssetId) ||
        (current != null &&
            current.expiresAt.isAfter(
              DateTime.now().toUtc().add(const Duration(seconds: 30)),
            )) ||
        loadingImages.contains(photo.imageAssetId)) {
      return;
    }
    loadingImages.add(photo.imageAssetId);
    notifyListeners();
    try {
      downloads[photo.imageAssetId] = await _repository.getDownloadIntent(
        photo.imageAssetId,
      );
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
    } finally {
      loadingImages.remove(photo.imageAssetId);
      notifyListeners();
    }
  }

  Future<BodyPhotoAssessment?> analyze(BodyProgressPhoto photo) async {
    if (analyzingPhotoId != null) return null;
    analyzingPhotoId = photo.id;
    errorMessage = null;
    notifyListeners();
    try {
      final assessment = await _repository.analyze(photo.id);
      photos = photos
          .map(
            (item) =>
                item.id == photo.id ? item.withAssessment(assessment) : item,
          )
          .toList(growable: false);
      return assessment;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return null;
    } finally {
      analyzingPhotoId = null;
      notifyListeners();
    }
  }

  Future<BodyPhotoAssessment?> compare(
    BodyProgressPhoto before,
    BodyProgressPhoto after,
  ) async {
    if (analyzingPhotoId != null) return null;
    analyzingPhotoId = after.id;
    comparison = null;
    errorMessage = null;
    notifyListeners();
    try {
      comparison = await _repository.compare(
        beforePhotoId: before.id,
        afterPhotoId: after.id,
      );
      return comparison;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return null;
    } finally {
      analyzingPhotoId = null;
      notifyListeners();
    }
  }

  Future<ProgressReport?> generateReport({int days = 30}) async {
    if (generatingReport) return null;
    generatingReport = true;
    errorMessage = null;
    notifyListeners();
    try {
      final report = await _repository.generatePhaseReport(days: days);
      reports = [report, ...reports.where((item) => item.id != report.id)];
      return report;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return null;
    } finally {
      generatingReport = false;
      notifyListeners();
    }
  }

  String _messageFor(ApiException error) => switch (error.code) {
    'BODY_IMAGE_ASSESSMENT_FAILED' => 'AI 无法可靠评估这张照片，请更换光线和角度后重试',
    'VISION_MODEL_BUSY' => 'AI 视觉模型当前繁忙，请稍等几秒后重试',
    'VISION_MODEL_UNAVAILABLE' => 'AI 视觉服务暂时不可用，请稍后重试',
    'BODY_IMAGE_NOT_READY' => '照片仍在处理中，请稍后重试',
    'IMAGE_STORAGE_UNAVAILABLE' => '图片服务暂时不可用，请检查网络后重试',
    'NETWORK_ERROR' => '无法连接后端，请确认服务仍在运行',
    _ => error.message,
  };
}
