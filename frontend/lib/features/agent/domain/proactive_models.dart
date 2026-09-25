class ProactiveSettings {
  const ProactiveSettings({
    required this.enabled,
    required this.categories,
    required this.frequency,
    required this.version,
  });

  factory ProactiveSettings.fromJson(Map<String, dynamic> json) =>
      ProactiveSettings(
        enabled: json['enabled'] as bool? ?? false,
        categories: Map<String, dynamic>.from(json['categories'] as Map? ?? {}),
        frequency: json['frequency'] as String? ?? 'important_only',
        version: json['version'] as int,
      );

  final bool enabled;
  final Map<String, dynamic> categories;
  final String frequency;
  final int version;

  bool get coachEnabled => enabled && categories['proactive_coach'] == true;
}

class ProactiveNotice {
  const ProactiveNotice({
    required this.id,
    required this.title,
    required this.body,
    required this.route,
    required this.kind,
    required this.feedbackRating,
  });

  factory ProactiveNotice.fromJson(Map<String, dynamic> json) {
    final data = Map<String, dynamic>.from(json['data'] as Map? ?? {});
    return ProactiveNotice(
      id: json['id'] as String,
      title: json['title'] as String,
      body: json['body'] as String,
      route: data['route'] as String? ?? 'agent',
      kind: data['kind'] as String? ?? 'general',
      feedbackRating: (data['feedback'] as Map?)?['rating'] as String?,
    );
  }

  final String id;
  final String title;
  final String body;
  final String route;
  final String kind;
  final String? feedbackRating;
}
