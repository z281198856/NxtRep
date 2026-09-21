enum BodyPhotoView {
  front('front', '正面'),
  side('side', '侧面'),
  back('back', '背面');

  const BodyPhotoView(this.apiName, this.label);
  final String apiName;
  final String label;

  static BodyPhotoView fromApi(String value) => values.firstWhere(
    (item) => item.apiName == value,
    orElse: () => BodyPhotoView.front,
  );
}

class BodyPhotoObservation {
  const BodyPhotoObservation({
    required this.category,
    required this.observation,
    required this.visualEvidence,
    required this.confidence,
  });

  factory BodyPhotoObservation.fromJson(Map<String, dynamic> json) =>
      BodyPhotoObservation(
        category: json['category'] as String? ?? 'other',
        observation: json['observation'] as String? ?? '',
        visualEvidence: json['visual_evidence'] as String? ?? '',
        confidence: json['confidence'] as String? ?? 'low',
      );

  final String category;
  final String observation;
  final String visualEvidence;
  final String confidence;
}

class BodyPhotoAssessment {
  const BodyPhotoAssessment({
    required this.summary,
    required this.observations,
    required this.trainingConsiderations,
    required this.recommendedNextSteps,
    required this.followUpQuestions,
    required this.professionalReviewRecommended,
    required this.disclaimer,
  });

  factory BodyPhotoAssessment.fromJson(Map<String, dynamic> json) =>
      BodyPhotoAssessment(
        summary: json['summary'] as String? ?? '',
        observations: (json['observations'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(BodyPhotoObservation.fromJson)
            .toList(growable: false),
        trainingConsiderations:
            (json['training_considerations'] as List<dynamic>? ?? const [])
                .whereType<String>()
                .toList(growable: false),
        recommendedNextSteps:
            (json['recommended_next_steps'] as List<dynamic>? ?? const [])
                .whereType<String>()
                .toList(growable: false),
        followUpQuestions:
            (json['follow_up_questions'] as List<dynamic>? ?? const [])
                .whereType<String>()
                .toList(growable: false),
        professionalReviewRecommended:
            json['professional_review_recommended'] as bool? ?? false,
        disclaimer: json['disclaimer'] as String? ?? '',
      );

  final String summary;
  final List<BodyPhotoObservation> observations;
  final List<String> trainingConsiderations;
  final List<String> recommendedNextSteps;
  final List<String> followUpQuestions;
  final bool professionalReviewRecommended;
  final String disclaimer;
}

class BodyProgressPhoto {
  const BodyProgressPhoto({
    required this.id,
    required this.imageAssetId,
    required this.capturedAt,
    required this.view,
    required this.version,
    this.notes,
    this.assessment,
  });

  factory BodyProgressPhoto.fromJson(Map<String, dynamic> json) {
    final rawAssessment = json['assessment'];
    return BodyProgressPhoto(
      id: json['id'] as String,
      imageAssetId: json['image_asset_id'] as String,
      capturedAt: DateTime.parse(json['captured_at'] as String),
      view: BodyPhotoView.fromApi(json['view'] as String? ?? 'unknown'),
      notes: json['notes'] as String?,
      assessment: rawAssessment is Map<String, dynamic>
          ? BodyPhotoAssessment.fromJson(rawAssessment)
          : null,
      version: json['version'] as int,
    );
  }

  final String id;
  final String imageAssetId;
  final DateTime capturedAt;
  final BodyPhotoView view;
  final String? notes;
  final BodyPhotoAssessment? assessment;
  final int version;

  BodyProgressPhoto withAssessment(BodyPhotoAssessment value) =>
      BodyProgressPhoto(
        id: id,
        imageAssetId: imageAssetId,
        capturedAt: capturedAt,
        view: view,
        version: version + 1,
        notes: notes,
        assessment: value,
      );
}

class ImageDownloadIntent {
  const ImageDownloadIntent({
    required this.url,
    required this.headers,
    required this.expiresAt,
  });

  factory ImageDownloadIntent.fromJson(Map<String, dynamic> json) =>
      ImageDownloadIntent(
        url: json['download_url'] as String,
        headers: (json['headers'] as Map<String, dynamic>? ?? const {}).map(
          (key, value) => MapEntry(key, value as String),
        ),
        expiresAt: DateTime.parse(json['expires_at'] as String),
      );

  final String url;
  final Map<String, String> headers;
  final DateTime expiresAt;
}

class ProgressReport {
  const ProgressReport({
    required this.id,
    required this.type,
    required this.periodStart,
    required this.periodEnd,
    required this.facts,
    required this.missingData,
    required this.recommendations,
  });

  factory ProgressReport.fromJson(Map<String, dynamic> json) => ProgressReport(
    id: json['id'] as String,
    type: json['report_type'] as String,
    periodStart: DateTime.parse(json['period_start'] as String),
    periodEnd: DateTime.parse(json['period_end'] as String),
    facts: json['facts'] as Map<String, dynamic>? ?? const {},
    missingData: (json['missing_data'] as List<dynamic>? ?? const [])
        .whereType<String>()
        .toList(growable: false),
    recommendations: (json['recommendations'] as List<dynamic>? ?? const [])
        .whereType<String>()
        .toList(growable: false),
  );

  final String id;
  final String type;
  final DateTime periodStart;
  final DateTime periodEnd;
  final Map<String, dynamic> facts;
  final List<String> missingData;
  final List<String> recommendations;

  Map<String, dynamic> get training =>
      facts['training'] as Map<String, dynamic>? ?? const {};
  Map<String, dynamic> get body =>
      facts['body'] as Map<String, dynamic>? ?? const {};
  Map<String, dynamic> get nutrition =>
      facts['nutrition'] as Map<String, dynamic>? ?? const {};
}
