const media = window.matchMedia("(max-width: 1040px)");
const source = document.getElementById("avatarCanvas");
const target = document.getElementById("mobileAvatarCanvas");
const sourcePerformance = document.getElementById("performanceLabel");
const sourceSequence = document.getElementById("sequenceLabel");
const targetPerformance = document.getElementById("mobilePerformanceLabel");
const targetSequence = document.getElementById("mobileSequenceLabel");
const targetContext = target ? target.getContext("2d") : null;

function syncMobilePreview() {
  if (
    media.matches
    && source
    && target
    && targetContext
    && sourcePerformance
    && sourceSequence
    && targetPerformance
    && targetSequence
  ) {
    targetContext.clearRect(0, 0, target.width, target.height);
    targetContext.drawImage(source, 0, 0, target.width, target.height);
    targetPerformance.textContent = sourcePerformance.textContent;
    targetSequence.textContent = sourceSequence.textContent;
  }
  window.requestAnimationFrame(syncMobilePreview);
}

window.requestAnimationFrame(syncMobilePreview);
