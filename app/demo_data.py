"""Scripted, fictional students for the sample class on the teacher dashboard.

Each entry is (first name, chapter, explanation, follow-up answers). They are
run through the real offline brain, so scores and misconceptions are computed,
not hard-coded. The mix is chosen to look like a real class: most students in
Photosynthesis think plants get food from soil.
"""

DEMO_CLASS_NAME = "Class 7B · Sample data"

# Photosynthesis explanations
P_SOIL = "Plant mitti se khana leta hai. Patte hare hote hain aur dhoop mein plant badhta hai."
P_SOIL_2 = "Paudha jad se mitti ka khana kheenchta hai aur paani bhi leta hai. Phir oxygen chhodta hai."
P_GOOD = ("Patte dhoop ki roshni se khana banate hain. Woh hawa se carbon dioxide aur jad se paani lete hain, "
          "aur glucose banate hain. Oxygen bahar nikalti hai.")
P_BREATH = "Photosynthesis mein plant saans leta hai, hawa andar leta hai aur oxygen chhodta hai."
P_SUN = "Plant dhoop khata hai, wahi uska khana hai. Patte hare hote hain."

P_GOOD_ANS = ["kyunki plant khud khana banata hai patton mein", "isliye raat ko nahi hota kyunki dhoop nahi hoti",
              "paani jad se patton tak jaata hai"]
P_MIXED_ANS = ["pata nahi", "pata nahi", "kyunki patte hare hote hain", "shayad paani se"]
P_WEAK_ANS = ["pata nahi", "pata nahi", "pata nahi", "pata nahi", "mitti se hi", "pata nahi"]

# Fractions explanations
F_BIG_DEN = "Fraction matlab hissa. 1/8 bada hai 1/4 se kyunki 8 bada number hai."
F_ADD = "1/2 aur 1/3 jodne ke liye upar wale aur neeche wale jodo, 2/5 aata hai."
F_LESS_ONE = "Fraction hamesha 1 se chhota hota hai, jaise roti ka tukda. Upar wala number tukde batata hai."
F_GOOD = ("Fraction poore ke barabar hisse hote hain. Neeche wala number batata hai kitne tukde kiye, upar wala kitne "
          "liye. 1/2 bada hai 1/4 se kyunki tukde bade hain.")

F_GOOD_ANS = ["kyunki tukde barabar hone chahiye", "neeche wala number batata hai kitne hisse",
              "isliye pehle denominator same karte hain"]
F_MIXED_ANS = ["pata nahi", "pata nahi", "kyunki tukde chhote hote hain", "number bada hai"]

# Gravity explanations
G_HEAVY = "Gravity ek force hai jo dharti lagati hai. Bhari cheez jaldi girti hai."
G_SPACE = "Gravity dharti kheenchti hai par space mein gravity nahi hoti isliye astronaut float karte hain."
G_GOOD = ("Gravity ek kheenchne wala bal hai. Dharti har cheez ko apni taraf kheenchti hai, chand ko bhi. "
          "Door jaane par gravity kam hoti hai.")

G_GOOD_ANS = ["kyunki hawa ki rukawat se farak padta hai", "isliye chand ghoomta hai", "mass zyada toh kheenchav zyada"]
G_MIXED_ANS = ["pata nahi", "pata nahi", "kyunki dharti kheenchti hai", "pata nahi", "pata nahi"]

DEMO_STUDENTS = [
    # Photosynthesis: 10 students, 6 with the soil misconception
    ("Aarav", "photosynthesis", P_SOIL, P_MIXED_ANS),
    ("Diya", "photosynthesis", P_GOOD, P_GOOD_ANS),
    ("Kabir", "photosynthesis", P_SOIL, P_WEAK_ANS),
    ("Meera", "photosynthesis", P_SOIL_2, P_MIXED_ANS),
    ("Rohan", "photosynthesis", P_BREATH, P_MIXED_ANS),
    ("Sana", "photosynthesis", P_SOIL, P_GOOD_ANS),
    ("Ishaan", "photosynthesis", P_SUN, P_WEAK_ANS),
    ("Ananya", "photosynthesis", P_GOOD, P_MIXED_ANS),
    ("Vivaan", "photosynthesis", P_SOIL_2, P_WEAK_ANS),
    ("Priya", "photosynthesis", P_SOIL, P_MIXED_ANS),
    # Fractions: 8 students
    ("Aarav", "fractions", F_BIG_DEN, F_MIXED_ANS),
    ("Diya", "fractions", F_GOOD, F_GOOD_ANS),
    ("Kabir", "fractions", F_ADD, F_MIXED_ANS),
    ("Meera", "fractions", F_BIG_DEN, F_GOOD_ANS),
    ("Rohan", "fractions", F_LESS_ONE, F_MIXED_ANS),
    ("Sana", "fractions", F_GOOD, F_MIXED_ANS),
    ("Ishaan", "fractions", F_BIG_DEN, F_MIXED_ANS),
    ("Priya", "fractions", F_ADD, F_GOOD_ANS),
    # Gravity: 6 students
    ("Diya", "gravity", G_GOOD, G_GOOD_ANS),
    ("Kabir", "gravity", G_HEAVY, G_MIXED_ANS),
    ("Meera", "gravity", G_SPACE, G_MIXED_ANS),
    ("Sana", "gravity", G_HEAVY, G_GOOD_ANS),
    ("Ananya", "gravity", G_HEAVY, G_MIXED_ANS),
    ("Vivaan", "gravity", G_SPACE, G_MIXED_ANS),
]
