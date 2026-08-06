export function createLabState() {
  return {
    emotion: {
      mood: "neutral",
      arousal: 0.5,
      valence: 0.0,
      talkativeness: 0.5,
      reactive: { joy: 0.0, amusement: 0.0, anger: 0.0, sadness: 0.0, fear: 0.0, surprise: 0.0, discomfort: 0.0, emotional_pressure: 0.0 },
    },
    context: {
      source_activity_id: "body-pose-lab",
      attention_target: "conversation_partner",
      engagement: 0.55,
      posture_tendency: "neutral",
      movement_energy: 0.32,
      gaze_freedom: 0.72,
    },
    candidates: [
      { candidate_id: "conversation_partner", x: 0.0, y: -0.08, salience: 0.82, novelty: 0.18, threat: 0.0, relevance: 0.94, stability: 0.88 },
      { candidate_id: "ambient_light", x: 0.62, y: -0.42, salience: 0.34, novelty: 0.66, threat: 0.0, relevance: 0.32, stability: 0.42 },
    ],
    latestFrame: null,
  };
}

export function applyEmotionPreset(state, preset) {
  state.emotion.mood = preset.mood;
  state.emotion.arousal = preset.arousal;
  state.emotion.valence = preset.valence;
  state.emotion.reactive.joy = preset.joy;
  state.emotion.reactive.surprise = preset.surprise;
  state.emotion.reactive.fear = preset.fear;
}

export function emotionPayload(state) {
  return structuredClone(state.emotion);
}

export function contextPayload(state) {
  return structuredClone(state.context);
}

export function candidatesPayload(state) {
  return { candidates: structuredClone(state.candidates) };
}
