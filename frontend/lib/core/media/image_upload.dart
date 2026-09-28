import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter_image_compress/flutter_image_compress.dart';
import 'package:http/http.dart' as http;

import '../network/api_client.dart';
import '../network/api_exception.dart';

class ImageUploadCapabilities {
  const ImageUploadCapabilities({
    required this.acceptedContentTypes,
    required this.convertBeforeUpload,
    required this.maxBytes,
    required this.maxPixels,
    required this.maxDimension,
  });

  factory ImageUploadCapabilities.fromJson(Map<String, dynamic> json) =>
      ImageUploadCapabilities(
        acceptedContentTypes: (json['accepted_content_types'] as List<dynamic>)
            .cast<String>(),
        convertBeforeUpload: (json['convert_before_upload'] as List<dynamic>)
            .cast<String>(),
        maxBytes: json['max_bytes'] as int,
        maxPixels: json['max_pixels'] as int,
        maxDimension: json['max_dimension'] as int,
      );

  final List<String> acceptedContentTypes;
  final List<String> convertBeforeUpload;
  final int maxBytes;
  final int maxPixels;
  final int maxDimension;

  ImageUploadCapabilities constrained({
    int? maxBytes,
    int? maxPixels,
    int? maxDimension,
  }) => ImageUploadCapabilities(
    acceptedContentTypes: acceptedContentTypes,
    convertBeforeUpload: convertBeforeUpload,
    maxBytes: math.min(this.maxBytes, maxBytes ?? this.maxBytes),
    maxPixels: math.min(this.maxPixels, maxPixels ?? this.maxPixels),
    maxDimension: math.min(
      this.maxDimension,
      maxDimension ?? this.maxDimension,
    ),
  );
}

class PreparedImageUpload {
  const PreparedImageUpload({
    required this.bytes,
    required this.contentType,
    required this.width,
    required this.height,
  });

  final Uint8List bytes;
  final String contentType;
  final int width;
  final int height;
}

class UploadedImage {
  const UploadedImage({
    required this.assetId,
    required this.bytes,
    required this.contentType,
  });

  final String assetId;
  final Uint8List bytes;
  final String contentType;
}

class ImagePreparationException implements Exception {
  const ImagePreparationException(this.message);

  final String message;
}

class MobileImagePreparer {
  const MobileImagePreparer();

  Future<PreparedImageUpload> prepare(
    Uint8List source,
    ImageUploadCapabilities capabilities,
  ) async {
    if (source.isEmpty) {
      throw const ImagePreparationException('图片内容为空，请重新选择');
    }

    final sourceType = detectContentType(source);
    if (sourceType == null) {
      throw const ImagePreparationException(
        '无法识别图片格式，请选择 JPG、PNG、WebP 或 HEIC 图片',
      );
    }
    final canUploadDirectly = capabilities.acceptedContentTypes.contains(
      sourceType,
    );
    final shouldConvert = capabilities.convertBeforeUpload.contains(sourceType);
    if (!canUploadDirectly && !shouldConvert) {
      throw const ImagePreparationException('当前图片格式不受支持，请换一张图片');
    }

    _ImageSize? sourceSize;
    try {
      sourceSize = await _readSize(source);
    } on Object {
      if (!shouldConvert) {
        throw const ImagePreparationException('无法读取图片，请重新选择');
      }
    }

    if (canUploadDirectly &&
        sourceSize != null &&
        _isWithinLimits(source, sourceSize, capabilities)) {
      return PreparedImageUpload(
        bytes: source,
        contentType: sourceType,
        width: sourceSize.width,
        height: sourceSize.height,
      );
    }

    var current = source;
    var currentSize = sourceSize;
    const qualities = <int>[88, 78, 68, 58, 48, 38, 30];
    for (var attempt = 0; attempt < qualities.length; attempt += 1) {
      final target = currentSize == null
          ? _ImageSize(capabilities.maxDimension, capabilities.maxDimension)
          : _fitWithinLimits(currentSize, capabilities, shrink: attempt >= 3);
      try {
        current = await FlutterImageCompress.compressWithList(
          current,
          minWidth: target.width,
          minHeight: target.height,
          quality: qualities[attempt],
          format: CompressFormat.jpeg,
          autoCorrectionAngle: true,
          keepExif: false,
        );
      } on Object {
        throw const ImagePreparationException('图片转换失败，请换一张图片后重试');
      }
      if (current.isEmpty) {
        throw const ImagePreparationException('图片转换失败，请换一张图片后重试');
      }

      try {
        currentSize = await _readSize(current);
      } on Object {
        throw const ImagePreparationException('转换后的图片无法读取，请重新选择');
      }
      if (_isWithinLimits(current, currentSize, capabilities)) {
        return PreparedImageUpload(
          bytes: current,
          contentType: 'image/jpeg',
          width: currentSize.width,
          height: currentSize.height,
        );
      }
    }

    throw const ImagePreparationException('图片过大，压缩后仍超过上传限制，请换一张图片');
  }

  static String? detectContentType(Uint8List bytes) {
    if (bytes.length >= 3 &&
        bytes[0] == 0xff &&
        bytes[1] == 0xd8 &&
        bytes[2] == 0xff) {
      return 'image/jpeg';
    }
    if (bytes.length >= 8 &&
        bytes[0] == 0x89 &&
        bytes[1] == 0x50 &&
        bytes[2] == 0x4e &&
        bytes[3] == 0x47 &&
        bytes[4] == 0x0d &&
        bytes[5] == 0x0a &&
        bytes[6] == 0x1a &&
        bytes[7] == 0x0a) {
      return 'image/png';
    }
    if (bytes.length >= 12 &&
        _ascii(bytes, 0, 4) == 'RIFF' &&
        _ascii(bytes, 8, 12) == 'WEBP') {
      return 'image/webp';
    }
    if (bytes.length >= 12 && _ascii(bytes, 4, 8) == 'ftyp') {
      const heifBrands = <String>{
        'heic',
        'heix',
        'hevc',
        'hevx',
        'mif1',
        'msf1',
      };
      final brand = _ascii(bytes, 8, 12);
      if (heifBrands.contains(brand)) return 'image/heic';
    }
    return null;
  }

  static String _ascii(Uint8List bytes, int start, int end) =>
      String.fromCharCodes(bytes.sublist(start, end));

  static bool _isWithinLimits(
    Uint8List bytes,
    _ImageSize size,
    ImageUploadCapabilities capabilities,
  ) =>
      bytes.length <= capabilities.maxBytes &&
      size.width <= capabilities.maxDimension &&
      size.height <= capabilities.maxDimension &&
      size.width * size.height <= capabilities.maxPixels;

  static _ImageSize _fitWithinLimits(
    _ImageSize source,
    ImageUploadCapabilities capabilities, {
    required bool shrink,
  }) {
    final dimensionScale =
        capabilities.maxDimension / math.max(source.width, source.height);
    final pixelScale = math.sqrt(
      capabilities.maxPixels / (source.width * source.height),
    );
    var scale = math.min(1.0, math.min(dimensionScale, pixelScale));
    if (shrink) scale *= 0.82;
    return _ImageSize(
      math.max(1, (source.width * scale).floor()),
      math.max(1, (source.height * scale).floor()),
    );
  }

  static Future<_ImageSize> _readSize(Uint8List bytes) async {
    final codec = await ui.instantiateImageCodec(bytes);
    try {
      final frame = await codec.getNextFrame();
      return _ImageSize(frame.image.width, frame.image.height);
    } finally {
      codec.dispose();
    }
  }
}

class ImageUploadRepository {
  ImageUploadRepository(
    this._apiClient, {
    http.Client? uploadClient,
    this._preparer = const MobileImagePreparer(),
  }) : _uploadClient = uploadClient ?? http.Client(),
       _ownsUploadClient = uploadClient == null;

  final ApiClient _apiClient;
  final http.Client _uploadClient;
  final bool _ownsUploadClient;
  final MobileImagePreparer _preparer;

  Future<ImageUploadCapabilities>? _capabilitiesRequest;

  Future<UploadedImage> uploadChatImage(Uint8List source) =>
      _uploadImage(source, purpose: 'chat_attachment');

  Future<UploadedImage> uploadTrainingPlanImage(Uint8List source) =>
      _uploadImage(
        source,
        purpose: 'training_plan',
        preferredMaxBytes: 2 * 1024 * 1024,
        preferredMaxPixels: 2048 * 2048,
        preferredMaxDimension: 2048,
      );

  Future<UploadedImage> uploadBodyProgressImage(Uint8List source) =>
      _uploadImage(
        source,
        purpose: 'body_progress',
        preferredMaxBytes: 1536 * 1024,
        preferredMaxPixels: 1440 * 1440,
        preferredMaxDimension: 1440,
      );

  Future<UploadedImage> uploadNutritionImage(Uint8List source) => _uploadImage(
    source,
    purpose: 'nutrition_entry',
    preferredMaxBytes: 2 * 1024 * 1024,
    preferredMaxPixels: 2048 * 2048,
    preferredMaxDimension: 2048,
  );

  Future<UploadedImage> _uploadImage(
    Uint8List source, {
    required String purpose,
    int? preferredMaxBytes,
    int? preferredMaxPixels,
    int? preferredMaxDimension,
  }) async {
    final serverCapabilities = await _capabilities();
    final capabilities = serverCapabilities.constrained(
      maxBytes: preferredMaxBytes,
      maxPixels: preferredMaxPixels,
      maxDimension: preferredMaxDimension,
    );
    late final PreparedImageUpload prepared;
    try {
      prepared = await _preparer.prepare(source, capabilities);
    } on ImagePreparationException catch (error) {
      throw ApiException(
        code: 'IMAGE_PREPARATION_FAILED',
        message: error.message,
      );
    }

    final intent = expectJsonObject(
      await _apiClient.post(
        '/media/images/upload-intents',
        body: {
          'purpose': purpose,
          'content_type': prepared.contentType,
          'content_length': prepared.bytes.length,
        },
      ),
      context: '图片上传接口',
    );
    final assetId = intent['asset_id'] as String;
    final uploadUrl = Uri.parse(intent['upload_url'] as String);
    final headers = (intent['headers'] as Map<String, dynamic>).map(
      (key, value) => MapEntry(key, value as String),
    );
    if (!headers.keys.any((key) => key.toLowerCase() == 'content-type')) {
      headers['Content-Type'] = prepared.contentType;
    }

    final request = http.Request('PUT', uploadUrl)
      ..headers.addAll(headers)
      ..bodyBytes = prepared.bytes
      ..followRedirects = false;
    late final http.StreamedResponse uploadResponse;
    try {
      uploadResponse = await _uploadClient.send(request);
    } on Object catch (error) {
      throw ApiException.network(error);
    }
    await uploadResponse.stream.drain<void>();
    if (uploadResponse.statusCode < HttpStatus.ok ||
        uploadResponse.statusCode >= HttpStatus.multipleChoices) {
      throw ApiException(
        statusCode: uploadResponse.statusCode,
        code: 'IMAGE_DIRECT_UPLOAD_FAILED',
        message: '图片上传失败，请检查网络后重试',
      );
    }

    final completed = expectJsonObject(
      await _apiClient.post(
        '/media/images/$assetId/complete',
        body: {
          'expected_content_type': prepared.contentType,
          'expected_content_length': prepared.bytes.length,
        },
      ),
      context: '图片校验接口',
    );
    if (completed['status'] != 'ready') {
      throw const ApiException(
        code: 'IMAGE_PROCESSING_FAILED',
        message: '图片处理失败，请换一张图片后重试',
      );
    }
    return UploadedImage(
      assetId: assetId,
      bytes: prepared.bytes,
      contentType: prepared.contentType,
    );
  }

  Future<ImageUploadCapabilities> _capabilities() {
    final existing = _capabilitiesRequest;
    if (existing != null) return existing;
    final request = _loadCapabilities();
    _capabilitiesRequest = request;
    return request.catchError((Object error) {
      if (identical(_capabilitiesRequest, request)) {
        _capabilitiesRequest = null;
      }
      throw error;
    });
  }

  Future<ImageUploadCapabilities> _loadCapabilities() async {
    final json = expectJsonObject(
      await _apiClient.get('/media/images/capabilities'),
      context: '图片能力接口',
    );
    return ImageUploadCapabilities.fromJson(json);
  }

  void close() {
    if (_ownsUploadClient) _uploadClient.close();
  }
}

class _ImageSize {
  const _ImageSize(this.width, this.height);

  final int width;
  final int height;
}
