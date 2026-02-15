# Firebase Setup for Live Dashboard

## Quick Setup (5 minutes)

### 1. Create Firebase Project
1. Go to https://console.firebase.google.com
2. Click "Create a project"
3. Name it: `polymarket-bot` (or any name)
4. Disable Google Analytics (not needed)
5. Click Create

### 2. Create Realtime Database
1. In left menu, click "Build" → "Realtime Database"
2. Click "Create Database"
3. Choose location (any)
4. Select "Start in **test mode**" (allows public read/write for 30 days)
5. Click Enable

### 3. Get Database URL
1. Your database URL will look like: `https://polymarket-bot-xxxxx.firebaseio.com`
2. Copy this URL

### 4. Add to .env
Add this line to your `.env` file:
```
FIREBASE_URL=https://your-project.firebaseio.com
```

### 5. Done!
The bot will now push live data to Firebase, and the public site will read from it in real-time.

## Security Note
Test mode allows anyone to read/write for 30 days. After that, you'll need to set up proper security rules. For a read-only public dashboard, use these rules:

```json
{
  "rules": {
    "dashboard": {
      ".read": true,
      ".write": false
    }
  }
}
```

Then update the bot to use a Firebase Admin SDK with a service account for writes.
