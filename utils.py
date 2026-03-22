"""
utils.py - Fonctions utilitaires partagées
"""
import os
import base64
from PIL import Image
import io
from config import IMAGES_DIR, CURRENCY


def format_price(amount: float) -> str:
    """Formate un montant en devise locale."""
    return f"{amount:,.2f} {CURRENCY}"


def save_uploaded_image(uploaded_file, part_number: str) -> str:
    """
    Sauvegarde une image uploadée dans data/images/.
    Retourne le chemin relatif.
    """
    ext = uploaded_file.name.split(".")[-1].lower()
    filename = f"{part_number.replace('/', '_')}.{ext}"
    path = os.path.join(IMAGES_DIR, filename)
    img = Image.open(uploaded_file)
    img.thumbnail((400, 400))
    img.save(path)
    return path


def get_image_base64(image_path: str) -> str | None:
    """Retourne une image encodée en base64 pour affichage HTML."""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        ext = image_path.split(".")[-1].lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    except Exception:
        return None


def placeholder_image_html(size=120) -> str:
    """Retourne un placeholder SVG si pas d'image."""
    return f"""
    <svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">
      <rect width="100%" height="100%" fill="#e0e0e0" rx="8"/>
      <text x="50%" y="50%" font-size="12" fill="#888"
            text-anchor="middle" dominant-baseline="middle">📷 Pas d'image</text>
    </svg>
    """


def get_part_image_html(image_path: str, size=120) -> str:
    """Retourne balise HTML image ou placeholder."""
    b64 = get_image_base64(image_path)
    if b64:
        return f'<img src="{b64}" width="{size}" height="{size}" style="object-fit:cover;border-radius:8px;">'
    return placeholder_image_html(size)


def validate_vin(vin: str) -> bool:
    """Vérifie basiquement qu'un VIN a 17 caractères alphanumériques."""
    vin = vin.strip().upper()
    if len(vin) != 17:
        return False
    forbidden = set("IOQ")
    return all(c.isalnum() and c not in forbidden for c in vin)


def get_categories() -> list:
    """Retourne la liste des catégories de pièces."""
    return [
        "Moteur", "Freinage", "Suspension", "Transmission",
        "Électricité", "Carrosserie", "Refroidissement",
        "Échappement", "Climatisation", "Filtration",
        "Éclairage", "Accessoires", "Autre"
    ]


def get_makes() -> list:
    """Retourne les marques du parc algérien."""
    return [
        "Renault", "Peugeot", "Citroën", "Hyundai",
        "Kia", "Toyota", "Chevrolet", "Volkswagen",
        "Ford", "Nissan", "Dacia", "Fiat",
        "Mercedes", "BMW", "Suzuki", "Autre"
    ]


def get_payment_methods() -> list:
    return ["Espèces", "Carte bancaire", "Virement", "Chèque"]


def get_expense_categories() -> list:
    return [
        "Achat fournisseur", "Loyer", "Électricité", "Eau",
        "Transport", "Salaires", "Publicité", "Maintenance",
        "Taxes et impôts", "Autre"
    ]
