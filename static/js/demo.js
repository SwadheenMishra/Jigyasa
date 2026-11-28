/* Demo mode: a scripted Hinglish student explains Photosynthesis, with the
 * classic "plants eat soil" misconception.
 *
 * Only the student's side is scripted. Every line is sent to the real API
 * and answered by whichever brain is active, so judges see real targeted
 * questions, hints and scoring — with no microphone and no API key.
 *
 * Answers are chosen by the question's target concept/misconception id, so
 * the script still makes sense if the AI brain asks in a different order.
 * text = shown (Roman Hinglish), dev = spoken (Devanagari, for a Hindi voice).
 */
(function () {
  "use strict";

  const CHAPTER = "photosynthesis";

  const EXPLANATION = {
    text: "Photosynthesis mein plant mitti se khana leta hai. Patte hare hote hain aur dhoop mein plant badhta hai.",
    dev: "फोटोसिंथेसिस में प्लांट मिट्टी से खाना लेता है. पत्ते हरे होते हैं और धूप में प्लांट बढ़ता है.",
  };

  const ANSWERS = {
    // Targeted first: the misconception. First a "pata nahi" (shows the hint), then real thinking.
    food_from_soil: [
      { text: "Pata nahi...", dev: "पता नहीं..." },
      { text: "Hmm, shayad kyunki plant mitti nahi khata. Woh hawa aur paani se khud khana banata hai?",
        dev: "हम्म, शायद क्योंकि प्लांट मिट्टी नहीं खाता. वो हवा और पानी से खुद खाना बनाता है?" },
    ],
    carbon_dioxide: [
      { text: "Haan! Hawa se carbon dioxide leta hai, kyunki usi se khana banta hai.",
        dev: "हाँ! हवा से कार्बन डाइऑक्साइड लेता है, क्योंकि उसी से खाना बनता है." },
    ],
    water: [
      { text: "Jad se paani patton tak jaata hai, isliye paani zaroori hai.",
        dev: "जड़ से पानी पत्तों तक जाता है, इसलिए पानी ज़रूरी है." },
    ],
    oxygen: [
      { text: "Oxygen bahar chhodta hai, isliye hum saans le paate hain.",
        dev: "ऑक्सीजन बाहर छोड़ता है, इसलिए हम सांस ले पाते हैं." },
    ],
    sunlight: [
      { text: "Raat ko nahi hota, kyunki dhoop nahi hoti.", dev: "रात को नहीं होता, क्योंकि धूप नहीं होती." },
    ],
    chlorophyll: [
      { text: "Patte hare hote hain kyunki unme chlorophyll hota hai, jo dhoop pakadta hai.",
        dev: "पत्ते हरे होते हैं क्योंकि उनमें क्लोरोफिल होता है, जो धूप पकड़ता है." },
    ],
    glucose: [
      { text: "Plant glucose banata hai, matlab apna khana.", dev: "प्लांट ग्लूकोज़ बनाता है, मतलब अपना खाना." },
    ],
    _default: [
      { text: "Kyunki patte dhoop, hawa aur paani se khana banate hain.",
        dev: "क्योंकि पत्ते धूप, हवा और पानी से खाना बनाते हैं." },
    ],
  };

  /** A fresh scripted student. next(stage, targetId) -> {text, dev}. */
  function createDemo() {
    const used = {};
    return {
      chapter: CHAPTER,
      language: "hinglish",
      next(stage, targetId) {
        if (stage === "explain") return EXPLANATION;
        const key = ANSWERS[targetId] ? targetId : "_default";
        const list = ANSWERS[key];
        const i = used[key] || 0;
        used[key] = i + 1;
        return list[Math.min(i, list.length - 1)];
      },
    };
  }

  window.JDemo = { createDemo };
})();
