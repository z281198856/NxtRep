class ApiConfig {
  ApiConfig({Uri? baseUri}) : baseUri = baseUri ?? Uri.parse(defaultBaseUrl);

  static const String defaultBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000/api/v1',
  );

  final Uri baseUri;

  Uri resolve(String path) {
    final normalizedBase = baseUri.toString().endsWith('/')
        ? baseUri
        : Uri.parse('${baseUri.toString()}/');
    final normalizedPath = path.startsWith('/') ? path.substring(1) : path;
    return normalizedBase.resolve(normalizedPath);
  }
}
