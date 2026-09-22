import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../../core/theme/app_theme.dart';

enum FoodVisualCategory {
  protein,
  grain,
  vegetable,
  fruit,
  dairy,
  beverage,
  snack,
  generic,
}

FoodVisualCategory foodVisualCategory(String name, [String? brand]) {
  final value = '${name.toLowerCase()} ${brand?.toLowerCase() ?? ''}';
  bool containsAny(Iterable<String> words) =>
      words.any((word) => value.contains(word));

  if (containsAny(const [
    '奶',
    '酸奶',
    '乳',
    '芝士',
    '奶酪',
    'milk',
    'yogurt',
    'cheese',
    'dairy',
  ])) {
    return FoodVisualCategory.dairy;
  }
  if (containsAny(const [
    '鸡',
    '牛',
    '羊',
    '猪',
    '鱼',
    '虾',
    '蛋',
    '肉',
    '豆腐',
    '豆干',
    'protein',
    'chicken',
    'beef',
    'pork',
    'fish',
    'egg',
    'tofu',
  ])) {
    return FoodVisualCategory.protein;
  }
  if (containsAny(const [
    '米',
    '饭',
    '面',
    '燕麦',
    '麦片',
    '面包',
    '馒头',
    '玉米',
    '土豆',
    '红薯',
    'rice',
    'oat',
    'bread',
    'pasta',
    'noodle',
    'potato',
  ])) {
    return FoodVisualCategory.grain;
  }
  if (containsAny(const [
    '菜',
    '西兰花',
    '菠菜',
    '生菜',
    '番茄',
    '黄瓜',
    '胡萝卜',
    '菌',
    '蘑菇',
    'vegetable',
    'broccoli',
    'salad',
    'tomato',
    'carrot',
  ])) {
    return FoodVisualCategory.vegetable;
  }
  if (containsAny(const [
    '果',
    '苹果',
    '香蕉',
    '橙',
    '梨',
    '桃',
    '莓',
    '葡萄',
    'fruit',
    'apple',
    'banana',
    'orange',
    'berry',
  ])) {
    return FoodVisualCategory.fruit;
  }
  if (containsAny(const [
    '水',
    '茶',
    '咖啡',
    '饮料',
    '果汁',
    '可乐',
    'coffee',
    'tea',
    'juice',
    'drink',
    'water',
  ])) {
    return FoodVisualCategory.beverage;
  }
  if (containsAny(const [
    '饼干',
    '巧克力',
    '蛋糕',
    '薯片',
    '零食',
    'cookie',
    'cake',
    'snack',
    'chocolate',
  ])) {
    return FoodVisualCategory.snack;
  }
  return FoodVisualCategory.generic;
}

class FoodLineArt extends StatelessWidget {
  const FoodLineArt({
    super.key,
    required this.name,
    this.brand,
    this.size = 52,
  });

  final String name;
  final String? brand;
  final double size;

  @override
  Widget build(BuildContext context) {
    final category = foodVisualCategory(name, brand);
    final palette = _palette(category);
    return Semantics(
      image: true,
      label: '$name 线描食品插图',
      child: SizedBox.square(
        dimension: size,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: palette.background,
            borderRadius: BorderRadius.circular(size * 0.3),
          ),
          child: Padding(
            padding: EdgeInsets.all(size * 0.16),
            child: CustomPaint(
              painter: _FoodLinePainter(
                category: category,
                color: palette.stroke,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

({Color stroke, Color background}) _palette(FoodVisualCategory category) =>
    switch (category) {
      FoodVisualCategory.protein => (
        stroke: AppColors.primary,
        background: AppColors.primarySoft,
      ),
      FoodVisualCategory.grain => (
        stroke: AppColors.amber,
        background: AppColors.amberSoft,
      ),
      FoodVisualCategory.vegetable => (
        stroke: AppColors.mint,
        background: AppColors.mintSoft,
      ),
      FoodVisualCategory.fruit => (
        stroke: const Color(0xFFE86E4D),
        background: const Color(0xFFFFEFEA),
      ),
      FoodVisualCategory.dairy => (
        stroke: AppColors.indigo,
        background: AppColors.indigoSoft,
      ),
      FoodVisualCategory.beverage => (
        stroke: const Color(0xFF2C8AA0),
        background: const Color(0xFFE9F6F8),
      ),
      FoodVisualCategory.snack => (
        stroke: const Color(0xFF9A6A3A),
        background: const Color(0xFFF9F0E7),
      ),
      FoodVisualCategory.generic => (
        stroke: AppColors.muted,
        background: const Color(0xFFF1F2F6),
      ),
    };

class _FoodLinePainter extends CustomPainter {
  const _FoodLinePainter({required this.category, required this.color});

  final FoodVisualCategory category;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 64, size.height / 64);
    final line = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3.2
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final detail = Paint()
      ..color = color.withValues(alpha: 0.72)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.1
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    switch (category) {
      case FoodVisualCategory.protein:
        _drawProtein(canvas, line, detail);
      case FoodVisualCategory.grain:
        _drawGrain(canvas, line, detail);
      case FoodVisualCategory.vegetable:
        _drawVegetable(canvas, line, detail);
      case FoodVisualCategory.fruit:
        _drawFruit(canvas, line, detail);
      case FoodVisualCategory.dairy:
        _drawDairy(canvas, line, detail);
      case FoodVisualCategory.beverage:
        _drawBeverage(canvas, line, detail);
      case FoodVisualCategory.snack:
        _drawSnack(canvas, line, detail);
      case FoodVisualCategory.generic:
        _drawGeneric(canvas, line, detail);
    }
    canvas.restore();
  }

  void _drawProtein(Canvas canvas, Paint line, Paint detail) {
    final meat = Path()
      ..moveTo(38, 14)
      ..cubicTo(51, 16, 56, 28, 50, 39)
      ..cubicTo(45, 48, 31, 50, 23, 42)
      ..cubicTo(16, 35, 20, 23, 28, 18)
      ..cubicTo(31, 16, 34, 14, 38, 14);
    canvas.drawPath(meat, line);
    canvas.drawLine(const Offset(23, 42), const Offset(14, 51), line);
    canvas.drawCircle(const Offset(11, 54), 4, line);
    canvas.drawCircle(const Offset(17, 56), 4, line);
    canvas.drawArc(
      const Rect.fromLTWH(29, 22, 15, 13),
      -0.4,
      math.pi * 1.1,
      false,
      detail,
    );
  }

  void _drawGrain(Canvas canvas, Paint line, Paint detail) {
    final bowl = Path()
      ..moveTo(10, 31)
      ..quadraticBezierTo(13, 52, 32, 54)
      ..quadraticBezierTo(51, 52, 54, 31)
      ..close();
    canvas.drawPath(bowl, line);
    canvas.drawArc(
      const Rect.fromLTWH(10, 20, 44, 22),
      math.pi,
      math.pi,
      false,
      line,
    );
    for (final center in const [
      Offset(20, 29),
      Offset(28, 25),
      Offset(36, 29),
      Offset(44, 25),
    ]) {
      canvas.drawOval(
        Rect.fromCenter(center: center, width: 6, height: 3),
        detail,
      );
    }
    canvas.drawLine(const Offset(22, 55), const Offset(42, 55), detail);
  }

  void _drawVegetable(Canvas canvas, Paint line, Paint detail) {
    canvas.drawLine(const Offset(31, 30), const Offset(31, 55), line);
    canvas.drawLine(const Offset(39, 29), const Offset(43, 55), line);
    for (final circle in const [
      (Offset(22, 25), 10.0),
      (Offset(33, 17), 12.0),
      (Offset(45, 25), 10.0),
      (Offset(34, 29), 11.0),
    ]) {
      canvas.drawCircle(circle.$1, circle.$2, line);
    }
    canvas.drawLine(const Offset(31, 43), const Offset(24, 49), detail);
    canvas.drawLine(const Offset(40, 44), const Offset(48, 49), detail);
  }

  void _drawFruit(Canvas canvas, Paint line, Paint detail) {
    final apple = Path()
      ..moveTo(31, 22)
      ..cubicTo(22, 14, 12, 23, 15, 37)
      ..cubicTo(18, 52, 27, 57, 32, 51)
      ..cubicTo(38, 57, 47, 52, 50, 37)
      ..cubicTo(53, 23, 42, 14, 33, 22)
      ..close();
    canvas.drawPath(apple, line);
    canvas.drawLine(const Offset(32, 21), const Offset(34, 11), line);
    final leaf = Path()
      ..moveTo(35, 14)
      ..quadraticBezierTo(45, 8, 49, 14)
      ..quadraticBezierTo(42, 19, 35, 14);
    canvas.drawPath(leaf, detail);
    canvas.drawArc(
      const Rect.fromLTWH(22, 30, 20, 15),
      0.2,
      math.pi * 0.7,
      false,
      detail,
    );
  }

  void _drawDairy(Canvas canvas, Paint line, Paint detail) {
    final carton = Path()
      ..moveTo(17, 19)
      ..lineTo(43, 19)
      ..lineTo(50, 28)
      ..lineTo(50, 56)
      ..lineTo(17, 56)
      ..close();
    canvas.drawPath(carton, line);
    canvas.drawLine(const Offset(43, 19), const Offset(43, 56), detail);
    canvas.drawLine(const Offset(17, 19), const Offset(24, 10), line);
    canvas.drawLine(const Offset(24, 10), const Offset(42, 10), line);
    canvas.drawLine(const Offset(42, 10), const Offset(50, 28), line);
    canvas.drawCircle(const Offset(31, 38), 8, detail);
    canvas.drawArc(
      const Rect.fromLTWH(25, 32, 12, 12),
      -0.7,
      math.pi * 1.3,
      false,
      detail,
    );
  }

  void _drawBeverage(Canvas canvas, Paint line, Paint detail) {
    final cup = Path()
      ..moveTo(15, 20)
      ..lineTo(49, 20)
      ..lineTo(45, 55)
      ..lineTo(20, 55)
      ..close();
    canvas.drawPath(cup, line);
    canvas.drawLine(const Offset(37, 8), const Offset(31, 43), line);
    canvas.drawLine(const Offset(37, 8), const Offset(47, 8), line);
    canvas.drawPath(
      Path()
        ..moveTo(21, 36)
        ..quadraticBezierTo(27, 31, 33, 36)
        ..quadraticBezierTo(39, 41, 45, 36),
      detail,
    );
  }

  void _drawSnack(Canvas canvas, Paint line, Paint detail) {
    final cookie = Path()
      ..moveTo(49, 18)
      ..cubicTo(55, 28, 54, 42, 45, 50)
      ..cubicTo(34, 59, 17, 53, 12, 40)
      ..cubicTo(7, 27, 16, 13, 30, 11)
      ..cubicTo(35, 18, 42, 20, 49, 18)
      ..close();
    canvas.drawPath(cookie, line);
    for (final center in const [
      Offset(25, 24),
      Offset(39, 31),
      Offset(24, 42),
      Offset(42, 45),
    ]) {
      canvas.drawCircle(center, 2.5, detail);
    }
  }

  void _drawGeneric(Canvas canvas, Paint line, Paint detail) {
    canvas.drawCircle(const Offset(32, 33), 19, line);
    canvas.drawCircle(const Offset(32, 33), 12, detail);
    canvas.drawLine(const Offset(8, 14), const Offset(8, 53), line);
    canvas.drawLine(const Offset(4, 14), const Offset(4, 29), detail);
    canvas.drawLine(const Offset(12, 14), const Offset(12, 29), detail);
    canvas.drawLine(const Offset(56, 14), const Offset(56, 53), line);
    canvas.drawArc(
      const Rect.fromLTWH(50, 13, 12, 18),
      0,
      math.pi,
      false,
      detail,
    );
  }

  @override
  bool shouldRepaint(covariant _FoodLinePainter oldDelegate) =>
      oldDelegate.category != category || oldDelegate.color != color;
}
