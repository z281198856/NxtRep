class WaterEntry {
  const WaterEntry({
    required this.id,
    required this.amountMl,
    required this.consumedAt,
  });

  factory WaterEntry.fromJson(Map<String, dynamic> json) => WaterEntry(
    id: json['id'] as String,
    amountMl: (json['amount_ml'] as num).toInt(),
    consumedAt: DateTime.parse(json['consumed_at'] as String),
  );

  final String id;
  final int amountMl;
  final DateTime consumedAt;
}
