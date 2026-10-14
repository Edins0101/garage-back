from tests.conftest import login


def _list(client, headers, title="Super"):
    return client.post("/api/lists", json={"title": title, "kind": "shopping"}, headers=headers).json()


def test_items_link_to_owner_catalog_and_autocomplete(client, fake_storage):
    h = login(client, "ana@correo.com")
    lst = _list(client, h)
    a = client.post(f"/api/lists/{lst['id']}/items", json={"text": "Leche"}, headers=h).json()
    b = client.post(f"/api/lists/{lst['id']}/items", json={"text": "  léche "}, headers=h).json()
    assert a["productId"] and a["productId"] == b["productId"]  # mismo producto (sin tildes ni espacios)

    client.post(f"/api/lists/{lst['id']}/items", json={"text": "Lentejas"}, headers=h)
    client.post(f"/api/lists/{lst['id']}/items", json={"text": "Pan de leche"}, headers=h)
    names = [p["name"] for p in client.get(f"/api/lists/{lst['id']}/products?q=le", headers=h).json()]
    assert names[:2] == ["Leche", "Lentejas"] and "Pan de leche" in names  # primero los que empiezan con "le"

    # Otra lista del mismo dueño usa el mismo catálogo.
    other = _list(client, h, "Otra")
    c = client.post(f"/api/lists/{other['id']}/items", json={"text": "LECHE"}, headers=h).json()
    assert c["productId"] == a["productId"]


def test_product_photo_upload_flow(client, fake_storage):
    h = login(client, "ana@correo.com")
    lst = _list(client, h)
    item = client.post(f"/api/lists/{lst['id']}/items", json={"text": "Leche"}, headers=h).json()

    upload = client.post("/api/uploads", json={"listId": lst["id"], "contentType": "image/jpeg"}, headers=h).json()
    assert upload["uploadUrl"].startswith("https://") and upload["key"].endswith(".jpg")

    # Sin subir el archivo no se puede adjuntar.
    path = f"/api/lists/{lst['id']}/products/{item['productId']}/image"
    assert client.put(path, json={"key": upload["key"]}, headers=h).status_code == 400

    fake_storage.put(upload["key"], size=150_000)
    product = client.put(path, json={"key": upload["key"]}, headers=h).json()
    assert product["image"]["source"] == "product" and product["image"]["key"] == upload["key"]

    # El elemento muestra la foto del producto con enlace firmado.
    shown = client.get(f"/api/lists/{lst['id']}", headers=h).json()["items"][0]["image"]
    assert shown["source"] == "product" and "sig=" in shown["url"]

    # Reemplazarla por una URL borra la foto subida.
    product = client.put(path, json={"url": "https://ejemplo.com/leche.jpg"}, headers=h).json()
    assert product["image"]["url"] == "https://ejemplo.com/leche.jpg"
    assert upload["key"] not in fake_storage.objects

    assert client.put(path, json={"url": "http://inseguro.com/x.jpg"}, headers=h).status_code == 422
    assert client.delete(path, headers=h).json()["image"] is None


def test_item_photo_overrides_product_and_is_cleaned(client, fake_storage):
    h = login(client, "ana@correo.com")
    lst = _list(client, h)
    item = client.post(f"/api/lists/{lst['id']}/items", json={"text": "Café"}, headers=h).json()
    client.put(
        f"/api/lists/{lst['id']}/products/{item['productId']}/image",
        json={"url": "https://ejemplo.com/cafe.jpg"},
        headers=h,
    )

    up = client.post("/api/uploads", json={"listId": lst["id"]}, headers=h).json()
    fake_storage.put(up["key"])
    own = client.put(f"/api/lists/{lst['id']}/items/{item['id']}/image", json={"key": up["key"]}, headers=h).json()
    assert own["image"]["source"] == "item"

    # Al quitar la foto propia vuelve la del producto.
    back = client.delete(f"/api/lists/{lst['id']}/items/{item['id']}/image", headers=h).json()
    assert back["image"]["source"] == "product" and up["key"] not in fake_storage.objects

    # Borrar el elemento borra su foto propia.
    up2 = client.post("/api/uploads", json={"listId": lst["id"]}, headers=h).json()
    fake_storage.put(up2["key"])
    client.put(f"/api/lists/{lst['id']}/items/{item['id']}/image", json={"key": up2["key"]}, headers=h)
    client.delete(f"/api/lists/{lst['id']}/items/{item['id']}", headers=h)
    assert up2["key"] not in fake_storage.objects


def test_upload_validation(client, fake_storage):
    h = login(client, "ana@correo.com")
    lst = _list(client, h)
    item = client.post(f"/api/lists/{lst['id']}/items", json={"text": "Pan"}, headers=h).json()
    path = f"/api/lists/{lst['id']}/products/{item['productId']}/image"

    big = client.post("/api/uploads", json={"listId": lst["id"]}, headers=h).json()
    fake_storage.put(big["key"], size=3 * 1024 * 1024)
    assert client.put(path, json={"key": big["key"]}, headers=h).status_code == 400
    assert big["key"] not in fake_storage.objects  # se borra la subida inválida

    not_image = client.post("/api/uploads", json={"listId": lst["id"]}, headers=h).json()
    fake_storage.put(not_image["key"], content_type="application/pdf")
    assert client.put(path, json={"key": not_image["key"]}, headers=h).status_code == 400

    # Una clave de otro catálogo no se puede adjuntar.
    assert client.put(path, json={"key": "owners/otro/x.jpg"}, headers=h).status_code == 400


def test_shared_list_uses_owner_catalog_with_permissions(client, fake_storage):
    owner = login(client, "ana@correo.com")
    lst = _list(client, owner)
    item = client.post(f"/api/lists/{lst['id']}/items", json={"text": "Huevos"}, headers=owner).json()

    editor = login(client, "beto@correo.com")
    viewer = login(client, "zoe@correo.com")
    client.post(f"/api/lists/{lst['id']}/members", json={"email": "beto@correo.com", "role": "editor"}, headers=owner)
    client.post(f"/api/lists/{lst['id']}/members", json={"email": "zoe@correo.com", "role": "viewer"}, headers=owner)

    # El editor agrega "huevos" y queda vinculado al catálogo de la dueña.
    by_editor = client.post(f"/api/lists/{lst['id']}/items", json={"text": "huevos"}, headers=editor).json()
    assert by_editor["productId"] == item["productId"]

    # El editor puede poner la foto; el viewer solo verla.
    up = client.post("/api/uploads", json={"listId": lst["id"]}, headers=editor).json()
    assert up["key"].startswith("owners/")
    fake_storage.put(up["key"])
    path = f"/api/lists/{lst['id']}/products/{item['productId']}/image"
    assert client.put(path, json={"key": up["key"]}, headers=editor).status_code == 200
    assert client.post("/api/uploads", json={"listId": lst["id"]}, headers=viewer).status_code == 403
    assert client.get(f"/api/lists/{lst['id']}/products", headers=viewer).status_code == 200

    stranger = login(client, "x@correo.com")
    assert client.get(f"/api/lists/{lst['id']}/products", headers=stranger).status_code == 404


def test_photos_disabled_without_storage(client):
    h = login(client, "ana@correo.com")
    lst = _list(client, h)
    r = client.post("/api/uploads", json={"listId": lst["id"]}, headers=h)
    assert r.status_code == 503 and r.json() == {"message": "Las fotos todavía no están configuradas"}
