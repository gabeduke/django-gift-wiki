const functions = require('firebase-functions');
const { onRequest } = require('firebase-functions/v2/https');
const admin = require('firebase-admin');
const path = require('path');
const fs = require('fs');

admin.initializeApp();

// Cloud Run service URL
const CLOUD_RUN_URL = process.env.CLOUD_RUN_URL || 'https://giftwiki-dev-tshpxht2la-ue.a.run.app';

/**
 * Create session cookie from ID token (Firebase recommended pattern)
 * This endpoint receives an ID token, verifies it, and creates a secure session cookie
 */
exports.sessionLogin = onRequest({
  cors: true,
  region: 'us-east1',
}, async (req, res) => {
  try {
    // Only allow POST requests
    if (req.method !== 'POST') {
      return res.status(405).json({ error: 'Method not allowed' });
    }

    const { idToken } = req.body;

    if (!idToken) {
      return res.status(400).json({ error: 'ID token is required' });
    }

    // Verify the ID token
    let decodedToken;
    try {
      decodedToken = await admin.auth().verifyIdToken(idToken);
    } catch (error) {
      console.error('ID token verification failed:', error.message);
      return res.status(401).json({ error: 'Invalid ID token' });
    }

    // Check if user signed in recently OR token was recently issued
    // This prevents ID token theft attacks while allowing token refreshes
    const authTime = decodedToken.auth_time;
    const tokenIssuedAt = decodedToken.iat;
    const currentTime = Math.floor(Date.now() / 1000);
    const fiveMinutes = 5 * 60;
    const timeSinceAuth = currentTime - authTime;
    const timeSinceTokenIssued = currentTime - tokenIssuedAt;

    console.log('Token validation check:', {
      authTime,
      tokenIssuedAt,
      currentTime,
      timeSinceAuth,
      timeSinceAuthMinutes: Math.floor(timeSinceAuth / 60),
      timeSinceTokenIssued,
      timeSinceTokenIssuedMinutes: Math.floor(timeSinceTokenIssued / 60),
      tokenExpiresAt: decodedToken.exp
    });

    // Allow if EITHER:
    // 1. User signed in recently (within 5 minutes) - prevents token theft
    // 2. Token was issued recently (within 5 minutes) - allows token refreshes
    // This handles both new sign-ins and cases where user was already signed in
    const isAuthRecent = timeSinceAuth < fiveMinutes;
    const isTokenFresh = timeSinceTokenIssued < fiveMinutes;

    if (!isAuthRecent && !isTokenFresh) {
      console.warn(`Token validation failed: auth_time is ${Math.floor(timeSinceAuth / 60)} minutes old, token issued ${Math.floor(timeSinceTokenIssued / 60)} minutes ago`);
      return res.status(401).json({
        error: 'Recent sign-in required',
        details: `Token is too old. Please sign in again.`
      });
    }

    console.log('Token validation passed:', { isAuthRecent, isTokenFresh });

    // Create session cookie (expires in 5 days)
    const expiresIn = 60 * 60 * 24 * 5; // 5 days in seconds
    let sessionCookie;
    try {
      sessionCookie = await admin.auth().createSessionCookie(idToken, { expiresIn });
    } catch (error) {
      console.error('Failed to create session cookie:', error.message);
      return res.status(500).json({ error: 'Failed to create session cookie' });
    }

    // Set the session cookie with secure flags
    // Firebase Hosting will forward __session cookie to Cloud Run
    // Important: Don't set domain attribute - let browser use default
    // This ensures cookie works with custom domains (giftwiki-dev.leetserve.com)
    const cookieOptions = {
      maxAge: expiresIn * 1000, // Convert to milliseconds
      httpOnly: true, // Prevents XSS attacks
      secure: req.secure || req.headers['x-forwarded-proto'] === 'https', // Set secure only if request is HTTPS
      sameSite: 'lax', // CSRF protection
      path: '/',
      // Explicitly don't set domain - browser will use request hostname
    };

    // If running in valid local development where we might not be HTTPS, allow insecure cookies
    // Note: Firebase Functions emulator sets process.env.FUNCTIONS_EMULATOR = true
    if (process.env.FUNCTIONS_EMULATOR === 'true' || process.env.NODE_ENV === 'development') {
      cookieOptions.secure = false;
      console.log('Running in dev mode/emulator, setting cookie secure=false');
    }

    const requestHost = req.get('host') || req.headers.host || 'unknown';
    console.log('Setting session cookie:', {
      requestHost: requestHost,
      maxAge: cookieOptions.maxAge,
      httpOnly: cookieOptions.httpOnly,
      secure: cookieOptions.secure,
      sameSite: cookieOptions.sameSite,
      path: cookieOptions.path,
      cookieLength: sessionCookie.length,
      cookiePreview: sessionCookie.substring(0, 20) + '...'
    });

    // Set cookie using Express cookie method
    res.cookie('__session', sessionCookie, cookieOptions);

    // Also set Set-Cookie header explicitly to ensure it's sent correctly
    // Format: name=value; Path=/; Max-Age=seconds; HttpOnly; Secure; SameSite=Lax
    let setCookieHeader = `__session=${sessionCookie}; Path=/; Max-Age=${expiresIn}; HttpOnly; SameSite=Lax`;
    if (cookieOptions.secure) {
      setCookieHeader += '; Secure';
    }
    res.setHeader('Set-Cookie', setCookieHeader);

    console.log('Cookie set via both res.cookie() and Set-Cookie header');

    return res.status(200).json({
      status: 'success',
      expiresIn: expiresIn,
      message: 'Session cookie created successfully'
    });

  } catch (error) {
    console.error('Session login error:', error);
    return res.status(500).json({ error: 'Internal server error' });
  }
});

/**
 * Proxy function that enforces Firebase Authentication
 * and forwards requests to Cloud Run with the ID token
 */
exports.proxyToCloudRun = onRequest({
  cors: true,
  region: 'us-east1',
}, async (req, res) => {
  try {
    // Get session cookie (Firebase Hosting forwards __session cookie)
    const cookieHeader = req.headers.cookie || '';
    const cookies = {};
    cookieHeader.split(';').forEach(cookie => {
      const parts = cookie.trim().split('=');
      if (parts.length === 2) {
        cookies[parts[0].trim()] = decodeURIComponent(parts[1]);
      }
    });

    const sessionCookie = cookies.__session || (req.cookies && req.cookies.__session);

    // No session cookie - serve auth page
    if (!sessionCookie) {
      // Check if this is already the auth page to prevent loops
      if (req.url === '/auth.html' || req.url.startsWith('/auth.html')) {
        const authPagePath = path.join(__dirname, '../firebase-public/auth.html');
        const authPage = fs.readFileSync(authPagePath, 'utf8');
        return res.status(200).type('text/html').send(authPage);
      }
      // For other pages, redirect to auth page
      return res.redirect(`/auth.html?next=${encodeURIComponent(req.url)}`);
    }

    console.log('Session cookie found, verifying...');

    // Verify session cookie (not ID token)
    let decodedToken;
    try {
      decodedToken = await admin.auth().verifySessionCookie(sessionCookie, true /* checkRevoked */);
    } catch (error) {
      // Invalid or revoked session cookie - redirect to auth page
      console.log('Session cookie verification failed:', error.message);
      return res.redirect(`/auth.html?next=${encodeURIComponent(req.url)}`);
    }

    // Session cookie valid - forward to Cloud Run
    // Forward the session cookie in the request
    console.log('Session cookie verified, forwarding to Cloud Run:', req.url);
    const url = new URL(req.url, CLOUD_RUN_URL);
    const fetch = require('node-fetch');

    // Forward cookies (especially __session cookie)
    const forwardedHeaders = {
      ...req.headers,
      'X-Forwarded-User': decodedToken.email || decodedToken.uid,
      'X-Forwarded-Email': decodedToken.email || '',
      'host': new URL(CLOUD_RUN_URL).host, // Set correct host header
    };

    // Ensure cookie header is forwarded
    if (cookieHeader) {
      forwardedHeaders['cookie'] = cookieHeader;
    }

    const response = await fetch(url.toString(), {
      method: req.method,
      headers: forwardedHeaders,
      body: req.method !== 'GET' && req.method !== 'HEAD' && req.body ? JSON.stringify(req.body) : undefined,
    });

    // Forward the response
    const data = await response.text();
    res.status(response.status);

    // Copy response headers (except ones we shouldn't forward)
    const headersToSkip = ['content-encoding', 'transfer-encoding', 'connection'];
    response.headers.forEach((value, key) => {
      if (!headersToSkip.includes(key.toLowerCase())) {
        res.setHeader(key, value);
      }
    });

    res.send(data);

  } catch (error) {
    console.error('Proxy error:', error);
    res.status(500).send(`
      <html>
        <body>
          <h1>Error</h1>
          <p>${error.message}</p>
        </body>
      </html>
    `);
  }
});
