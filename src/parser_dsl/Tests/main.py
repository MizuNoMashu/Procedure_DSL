import spacy
from spacy.cli import download

model_name = "en_core_web_sm"

# Check if the model is already installed
if not spacy.util.is_package(model_name):
    print(f"Downloading SpaCy model: {model_name}")
    download(model_name)
else:
    print(f"SpaCy model '{model_name}' is already installed.")
    
nlp = spacy.load("en_core_web_sm")

def generate_sentence(verb, source_object, destination_object):
    # Create a SpaCy Doc object with the input words
    doc = nlp(f"{verb} {source_object} {destination_object}")

    # Extract the subject, verb, and objects
    subject = doc[0].text
    verb = doc[1].text
    objects = " ".join(token.text for token in doc[2:])

    # Create a template and format it with the extracted parts
    template = f"{subject.capitalize()} {verb} {objects}."
    return template

# Example usage
verb = "place"
source_object = "frame"
destination_object = "table"

sentence = generate_sentence(verb, source_object, destination_object)
print(sentence)