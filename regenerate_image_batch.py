import argparse

from dotenv import load_dotenv

load_dotenv()

from image_batch import generate_existing_article_set


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--article-id', type=int, required=True)
    args = parser.parse_args()
    result = generate_existing_article_set(args.article_id, artifact_prefix='image-batch')
    print(f"IMAGE_BATCH_CREATED batch_id={result['batch_id']} article_id={args.article_id}")


if __name__ == '__main__':
    main()
