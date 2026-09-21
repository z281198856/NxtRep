import '../../../core/network/api_client.dart';
import '../domain/body_progress_models.dart';

class BodyProgressRepository {
  BodyProgressRepository(this._apiClient);

  final ApiClient _apiClient;

  Future<List<BodyProgressPhoto>> listPhotos() async {
    final value = await _apiClient.get(
      '/body/progress-photos',
      query: {'limit': '50'},
    );
    if (value is! List<dynamic>) {
      throw const FormatException('身体照片列表格式不正确');
    }
    return value
        .whereType<Map<String, dynamic>>()
        .map(BodyProgressPhoto.fromJson)
        .toList(growable: false);
  }

  Future<BodyProgressPhoto> createPhoto({
    required String imageAssetId,
    required DateTime capturedAt,
    required BodyPhotoView view,
    String? notes,
  }) async => BodyProgressPhoto.fromJson(
    expectJsonObject(
      await _apiClient.post(
        '/body/progress-photos',
        body: {
          'image_asset_id': imageAssetId,
          'captured_at': capturedAt.toUtc().toIso8601String(),
          'view': view.apiName,
          'notes': notes,
          'assessment': null,
        },
      ),
      context: '身体照片保存接口',
    ),
  );

  Future<ImageDownloadIntent> getDownloadIntent(String assetId) async =>
      ImageDownloadIntent.fromJson(
        expectJsonObject(
          await _apiClient.get('/media/images/$assetId/download-intent'),
          context: '图片查看接口',
        ),
      );

  Future<BodyPhotoAssessment> analyze(String photoId) async =>
      BodyPhotoAssessment.fromJson(
        expectJsonObject(
          await _apiClient.post(
            '/body/progress-photos/$photoId/analysis-drafts',
            body: {'question': '请评估训练相关的体态和肌肉平衡，并给出可执行的训练建议。'},
            timeout: const Duration(seconds: 150),
          ),
          context: '身体照片评估接口',
        ),
      );

  Future<BodyPhotoAssessment> compare({
    required String beforePhotoId,
    required String afterPhotoId,
  }) async => BodyPhotoAssessment.fromJson(
    expectJsonObject(
      await _apiClient.post(
        '/body/progress-photos/compare',
        body: {
          'before_photo_id': beforePhotoId,
          'after_photo_id': afterPhotoId,
          'question': '请比较两张照片中可观察到的训练变化，说明局限并给出后续建议。',
        },
        timeout: const Duration(seconds: 150),
      ),
      context: '身体照片对比接口',
    ),
  );

  Future<List<ProgressReport>> listReports() async {
    final json = expectJsonObject(
      await _apiClient.get('/reports', query: {'page': '1', 'page_size': '20'}),
      context: '阶段报告列表接口',
    );
    return (json['list'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(ProgressReport.fromJson)
        .toList(growable: false);
  }

  Future<ProgressReport> generatePhaseReport({required int days}) async {
    final end = DateTime.now();
    final start = end.subtract(Duration(days: days - 1));
    return ProgressReport.fromJson(
      expectJsonObject(
        await _apiClient.post(
          '/reports/phase',
          body: {'period_start': _date(start), 'period_end': _date(end)},
        ),
        context: '阶段报告生成接口',
      ),
    );
  }

  String _date(DateTime value) =>
      '${value.year.toString().padLeft(4, '0')}-'
      '${value.month.toString().padLeft(2, '0')}-'
      '${value.day.toString().padLeft(2, '0')}';
}
