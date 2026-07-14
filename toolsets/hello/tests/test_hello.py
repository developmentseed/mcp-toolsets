from hello.tools import hello


def test_hello_default():
    assert hello.invoke({}) == {"message": "Hello, world!"}


def test_hello_name():
    assert hello.invoke({"name": "dev"}) == {"message": "Hello, dev!"}
